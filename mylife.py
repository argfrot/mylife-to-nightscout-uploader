import requests
import json
import time
import toml
from datetime import datetime,timedelta
import pytz
import os

from bs4 import BeautifulSoup

MY_ID = 'mylife uploader'
SETTINGS_TOML = 'settings.env'
BASE_URL = 'https://uk.mylife-software.net/'
SET_ID = False

def nightscout_headers(settings) :
    return {
        'api-secret': settings['nightscout']['API_SECRET'],
        'User-Agent': MY_ID,
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

def nightscout_last_treatment_time_ms(session, settings) :
    url = f'{settings["nightscout"]["URL"]}/api/v1/treatments?count=1'
    req = session.get(
        url,
        headers=nightscout_headers(settings),
        allow_redirects=True
    )
    if req.ok and req.text:
        resp = json.loads(req.text)
        if resp:
            return resp[0]['mills']

    return None

def upload_to_nightscout(treatments, session, settings) :
    if not treatments:
        return
    print(f'Uploading {len(treatments)} treatments to nightscout')
    url = f'{settings["nightscout"]["URL"]}/api/v1/treatments'
    req = session.post(url, json=treatments, headers=nightscout_headers(settings), allow_redirects=True)
    return req.status_code, req.text


def bg_check(glucose, created_at, glucoseType='Finger', _id=None):
    data = dict(
        eventType = 'BG Check',
        glucose = glucose,
        glucoseType = glucoseType,
        units = 'mmol',
        created_at = created_at.isoformat().replace("+00:00", "Z"),
        enteredBy = MY_ID,
    )
    if _id and SET_ID:
        data['_id'] = _id
    return data


def meal_bolus(insulin, glucose, glucoseType, carbs, created_at, _id=None):
    data = dict(
        eventType = 'Meal Bolus',
        insulin = insulin,
        carbs = carbs,
        created_at = created_at.isoformat().replace("+00:00", "Z"),
        enteredBy = MY_ID,
        #prebolus = 15, # minutes
    )
    if glucose:
        data.update(
            glucose = glucose,
            glucoseType = glucoseType, # 'Finger' or 'Sensor'
            units = 'mmol',
        )
    if _id and SET_ID:
        data['_id'] = _id
    return data


def correction_bolus(insulin, glucose, glucoseType, created_at, _id=None):
    data = dict(
        eventType = 'Correction Bolus',
        insulin = insulin,
        created_at = created_at.isoformat().replace("+00:00", "Z"),
        enteredBy = MY_ID,
    )
    if glucose:
        data.update(
            glucose = glucose,
            glucoseType = glucoseType, # 'Finger' or 'Sensor'
            units = 'mmol',
        )
    if _id and SET_ID:
        data['_id'] = _id
    return data


def correction_carbs(carbs, created_at, glucose=None, glucoseType='Finger', _id=None):
    data = dict(
        eventType = 'Carb Correction',
        carbs = carbs,
        created_at = created_at.isoformat().replace("+00:00", "Z"),
        enteredBy = MY_ID,
    )
    if glucose:
        data.update(
            glucose = glucose,
            glucoseType = glucoseType, # 'Finger' or 'Sensor'
            units = 'mmol',
        )
    if _id and SET_ID:
        data['_id'] = _id
    return data


# enteredBy: undefined
# eventType: Carb Correction
# glucose: 3.7
# targetTop: 0
# targetBottom: 0
# glucoseType: Finger
# carbs: 10
# units: mmol
# created_at: 2023-08-26T22:48:40.104Z


# enteredBy: undefined
# eventType: Meal Bolus
# glucose: 7
# targetTop: 0
# targetBottom: 0
# glucoseType: Finger
# carbs: 10
# insulin: 1
# preBolus: 0
# units: mmol
# created_at: 2023-08-26T18:25:11.282Z


# enteredBy: Jim
# eventType: Meal Bolus
# glucose: 10
# targetTop: 0
# targetBottom: 0
# glucoseType: Finger
# carbs: 15
# insulin: 1
# preBolus: 15
# notes: Bing bong
# units: mmol
# created_at: 2023-08-26T18:27:57.584Z


# eventType: Correction Bolus
# glucose: 12
# targetTop: 0
# targetBottom: 0
# glucoseType: Sensor
# insulin: 0.5
# units: mmol
# created_at: 2023-08-26T18:31:21.740Z


def save_session(session):
    with open('.session.cookies', 'w') as f:
        json.dump(requests.utils.dict_from_cookiejar(session.cookies), f)

def load_session(session):
    try:
        with open('.session.cookies', 'r') as f:
            cookies = requests.utils.cookiejar_from_dict(json.load(f))
            session.cookies.update(cookies)
    except FileNotFoundError:
        pass

def login(session, settings):
    login_form = session.get(BASE_URL)
    soup = BeautifulSoup(login_form.text, 'lxml')
    login_data = {
        '__EVENTVALIDATION': soup.find(id='__EVENTVALIDATION').get('value'),
        '__VIEWSTATE': soup.find(id='__VIEWSTATE').get('value'),
        '__VIEWSTATEGENERATOR': soup.find(id='__VIEWSTATEGENERATOR').get('value'),
        'ctl00$conContent$UserLogin$lgnMylifeLogin$UserName': settings['mylife']['EMAIL'],
        'ctl00$conContent$UserLogin$lgnMylifeLogin$Password': settings['mylife']['PASSWORD'],
        'ctl00$conContent$UserLogin$lgnMylifeLogin$LoginButton': 'Log in',
    }
    r2 = session.post(BASE_URL, data=login_data)

def get_logbook(session, settings):
    r3 = session.get(f'{BASE_URL}/Pages/Filterable/Logbook.aspx?ItemValue=logbook')
    s3 = BeautifulSoup(r3.text, 'lxml')
    rows = s3.find_all(class_=lambda x: x in ('rgRow', 'rgAltRow'))
    def to_dict(row):
        return {
            'day': row.find(class_='rgDay').text,
            'date': row.find(class_='rgDate').text,
            'time': row.find(class_='rgTime').text,
            'type': row.find(class_='rgEvent').text.strip(),
            'value': row.find(class_='rgValue').text,
            'info': row.find(class_='rgInformation').input.get('name') if row.find(class_='rgInformation').input else None,
            'note': row.find(class_='rgNote').text,
            'id': row.find('td', class_='').text,
        }
    processed = list(map(to_dict, rows))
    return processed

def post_logbook(session, settings):
    data = {
        'ctl00$conContent$ctl01$ddlTimeSpan': 'Today',
    }
    r3 = session.post(f'{BASE_URL}/Pages/Filterable/Logbook.aspx?ItemValue=logbook', data=data)
    s3 = BeautifulSoup(r3.text, 'lxml')
    rows = s3.find_all(class_=lambda x: x in ('rgRow', 'rgAltRow'))
    def to_dict(row):
        return {
            'day': row.find(class_='rgDay').text,
            'date': row.find(class_='rgDate').text,
            'time': row.find(class_='rgTime').text,
            'type': row.find(class_='rgEvent').text.strip(),
            'value': row.find(class_='rgValue').text,
            'info': row.find(class_='rgInformation').input.get('name') if row.find(class_='rgInformation').input else None,
            'note': row.find(class_='rgNote').text,
            'id': row.find('td', class_='').text,
        }
    processed = list(map(to_dict, rows))
    return processed


def get_utc_date(entry, settings):
    local_tz = pytz.timezone(settings['mylife']['TIMEZONE'])
    localtime = datetime.strptime(
        f'{entry["date"]} {entry["time"]}',
        '%d.%m.%y %H:%M'
    )
    local_dt = local_tz.localize(localtime)
    utc_dt = local_dt.astimezone(pytz.utc)
    return utc_dt


def group_by_interval(logs, settings, interval_minutes=5):
    def insert_datetime(entry):
        entry['datetime'] = get_utc_date(entry, settings)
        return entry

    dated_logs = list(map(insert_datetime, logs))

    sorted_logs = sorted(dated_logs, key=lambda x: x['datetime'], reverse=True)
    while sorted_logs:
        entry = sorted_logs.pop(0)
        t_end = entry['datetime']
        td = timedelta(minutes=interval_minutes)
        t_start = t_end - td

        entry_group = [entry]
        while sorted_logs and sorted_logs[0]['datetime'] > t_start:
            entry_group.append(sorted_logs.pop(0))

        yield entry_group


def find_entry(entry_type, entry_group):
    for entry in entry_group:
        if entry['type'] == entry_type:
            return entry
    return None


# this parsing should be made much more robust
def parse_bolus(value):
    return float(value[:-1]) # chop off the 'U' at the end

def parse_bg(value):
    return float(value.replace('mmol/L', '')) # drop the units

def parse_carbs(value):
    return int(value.replace('g carb', '')) # drop the units


def transformLogs(logs, settings):
    #pp list(f"{p['date']} {p['time']} - {p['type']}" for p in processed)
    treatments = []
    for entry_group in group_by_interval(logs, settings, interval_minutes=5):
        print(list(f"{e['date']} {e['time']} - {e['type']} {e['value']}" for e in entry_group))
        types = set(e['type'] for e in entry_group)

        # print(types)
        # print(len(entry_group))
        
        if ((len(entry_group) == 4 and types == set(['Bolus', 'Blood glucose', 'Blood glucose manual entry', 'Carbohydrates'])) or
           (len(entry_group) == 3 and types == set(['Bolus', 'Blood glucose', 'Carbohydrates']))):
            # meal bolus with finger prick
            print('meal bolus with finger prick')
            bolus = find_entry('Bolus', entry_group)
            bg = find_entry('Blood glucose', entry_group)
            #bg_manual = find_entry('Blood glucose manual entry', entry_group)
            carbs = find_entry('Carbohydrates', entry_group)

            treatment = meal_bolus(
                insulin=parse_bolus(bolus['value']),
                glucose=parse_bg(bg['value']),
                glucoseType='Finger',
                carbs=parse_carbs(carbs['value']),
                created_at=bolus['datetime'],
                _id=bolus['id']
            )
            treatments.append(treatment)

        elif len(entry_group) == 3 and types == set(['Bolus', 'Blood glucose manual entry', 'Carbohydrates']):
            # meal bolus with sensor reading
            print('meal bolus with sensor reading')
            bolus = find_entry('Bolus', entry_group)
            #bg = find_entry('Blood glucose', entry_group)
            bg_manual = find_entry('Blood glucose manual entry', entry_group)
            carbs = find_entry('Carbohydrates', entry_group)

            treatment = meal_bolus(
                insulin=parse_bolus(bolus['value']),
                glucose=parse_bg(bg_manual['value']),
                glucoseType='Sensor',
                carbs=parse_carbs(carbs['value']),
                created_at=bolus['datetime'],
                _id=bolus['id']
            )
            treatments.append(treatment)

        elif ((len(entry_group) == 2 and (types == set(['Bolus', 'Blood glucose']) or types == set(['Bolus', 'Blood glucose manual entry']))) or
             (len(entry_group) == 3 and types == set(['Bolus', 'Blood glucose', 'Blood glucose manual entry']))):
            # correction bolus
            print('correction bolus')
            bolus = find_entry('Bolus', entry_group)
            bg = find_entry('Blood glucose', entry_group)
            bg_manual = find_entry('Blood glucose manual entry', entry_group)

            treatment = correction_bolus(
                insulin=parse_bolus(bolus['value']),
                glucose=parse_bg(bg['value']) if bg else parse_bg(bg_manual['value']),
                glucoseType='Finger' if bg else 'Sensor',
                created_at=bolus['datetime'],
                _id=bolus['id']
            )
            treatments.append(treatment)

        elif len(entry_group) == 2 and types == set(['Carbohydrates', 'Bolus']):
            # meal bolus without glucose reading
            print('meal bolus without glucose reading')
            carbs = find_entry('Carbohydrates', entry_group)
            bolus = find_entry('Bolus', entry_group)

            treatment = meal_bolus(
                insulin=parse_bolus(bolus['value']),
                carbs=parse_carbs(carbs['value']),
                glucose=None,
                glucoseType=None,
                created_at=bolus['datetime'],
                _id=bolus['id']
            )
            treatments.append(treatment)

        elif len(entry_group) == 2 and (types == set(['Carbohydrates', 'Blood glucose']) or types == set(['Carbohydrates', 'Blood glucose manual entry'])):
            # carb correction
            print('carb correction')
            carbs = find_entry('Carbohydrates', entry_group)
            bg = find_entry('Blood glucose', entry_group)
            bg_manual = find_entry('Blood glucose manual entry', entry_group)

            treatment = correction_carbs(
                carbs=parse_carbs(carbs['value']),
                glucose=parse_bg(bg['value']) if bg else parse_bg(bg_manual['value']),
                glucoseType='Finger' if bg else 'Sensor',
                created_at=carbs['datetime'],
                _id=carbs['id']
            )
            treatments.append(treatment)

        elif types == set(['Carbohydrates']):
            # carb correction, bg from sensor
            print('carb correction')
            for carbs in entry_group:
                treatment = correction_carbs(
                    carbs=parse_carbs(carbs['value']),
                    created_at=carbs['datetime'],
                    _id=carbs['id']
                )
                treatments.append(treatment)

        elif types == set(['Blood glucose']) or types == set(['Blood glucose manual entry']) or types == set(['Blood glucose', 'Blood glucose manual entry']):
            # glucose reading
            print('glucose reading')
            for bg in entry_group:
                treatment = bg_check(
                    glucose=parse_bg(bg['value']),
                    glucoseType='Finger' if bg['type'] == 'Blood glucose' else 'Sensor',
                    created_at=bg['datetime'],
                    _id=bg['id']
                )
                treatments.append(treatment)

        elif types == set(['Bolus']):
            # correction bolus by eyeball
            print('correction bolus')
            for bolus in entry_group:
                bolus = find_entry('Bolus', entry_group)

                treatment = correction_bolus(
                    insulin=parse_bolus(bolus['value']),
                    glucose=None,
                    glucoseType=None,
                    created_at=bolus['datetime'],
                    _id=bolus['id']
                )
                treatments.append(treatment)

        else:
            print(f'UNKNOWN TREATMENT: {types}')

    return treatments


def run():
    settings = toml.load(SETTINGS_TOML)
    session = requests.session()
    load_session(session)

    last_treatment_ms = nightscout_last_treatment_time_ms(session, settings)

    login(session, settings)
    logs = get_logbook(session, settings)
    #post_logbook(session, settings)
    save_session(session)

    treatments = transformLogs(logs, settings)
    status, response = upload_to_nightscout(treatments, session, settings)
    if status != 200:
        print(treatments)
        print(response)
    print(status)

if __name__ == '__main__':
    run()



import requests

api_url = 'https://aiarena.net/api'
api_key = 'Token93ba08144f047986de6ef16c0e24f75fdf218a39'

url = api_url + '/bots'
headers = {
    'Authorization': api_key
}

jsonData = requests.get(url, headers=headers).json()

print(jsonData)


import requests
import matplotlib.pyplot as plt
import numpy as np
from statsmodels.stats.proportion import proportion_confint

competition_id = 7
confidence = 0.05
confidence_alpha = 0.15
length_max = 20
length_resolution = 1
bot_count = 5
round_limit = 1000
plot_dpi = 200
api_url = 'https://aiarena.net/api/'

bin_count = int(length_max / length_resolution)
file = open('./api_key.txt', mode='r')
api_key = file.read()
file.close()

headers = {
    'Authorization': 'Token {key}'.format(key=api_key)
}

def api(url, params={}):
    print(url, params)
    result = requests.get(url, headers=headers, params=params).json()
    return result

def api_list(url, params={}):
    results = []
    while url:
        result = api(url, params)
        results += result['results']
        url = result['next']
        params = {}
    return results

def winrate_intervals(participation):

    bins = [list() for _ in range(bin_count)]

    rounds = api(api_url + 'rounds', {
        'competition': participation['competition'],
        'ordering': '-started',
        'limit': round_limit,
    })['results']

    for round in rounds:

        matches = api_list(api_url + 'matches', {
            'round': round['id'],
            'bot': participation['bot'],
        })

        for match in matches:

            result = match['result']
            if not result:
                continue

            length = result['game_steps'] / (22.4 * 60)
            if length_max <= length:
                bin = len(bins) - 1
            else:
                bin = int(length / length_resolution)

            if result['winner'] == participation['bot']:
                outcome = 1.0
            elif result['type'] == 'Tie':
                outcome = 0.5
            else:
                outcome = 0.0

            bins[bin].append(outcome)

    winrates = [
        sum(l) / len(l)
        if l else 0.5
        for l in bins
    ]

    confidences = [
        proportion_confint(sum(l), len(l), alpha=confidence)
        if l else (0, 1)
        for l in bins
    ]

    intervals = [
        (w_min, w, w_max)
        for w, (w_min, w_max) in zip(winrates, confidences)
    ]

    return intervals

participations = api(api_url + 'competition-participations', {
    # 'bot': bot['id'],
    'competition': competition_id,
    'limit': bot_count,
    'ordering': '-elo'
})['results']


legend = []
for participation in participations:

    bot = api(api_url + 'bots/{id}'.format(id=participation['bot']))

    intervals = winrate_intervals(participation)

    x = np.arange(0, length_max, length_resolution)
    y_min, y, y_max = list(zip(*intervals))
    # plt.scatter(xs, ys)
    plt.xlabel('Game Length (min)')
    plt.ylabel('Winrate')
    legend.append(bot['name'])
    plt.plot(x, y)
    plt.fill_between(x, y_min, y_max, alpha=confidence_alpha)

plt.legend(legend)
plot_args = { 'dpi': plot_dpi }
plt.savefig("./publish/plot.svg", **plot_args)
plt.savefig("./publish/plot.png", **plot_args)
plt.show()
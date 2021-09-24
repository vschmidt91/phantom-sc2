
import requests
from statsmodels.stats.proportion import proportion_confint

confidence = 0.05
api_url = 'https://aiarena.net/api/'

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

def winrate_intervals(competition, match_to_categories, result_to_outcome, round_limit, length_bins):

    bins_by_category = {}

    rounds = api_list(api_url + 'rounds', {
        'competition': competition,
        'ordering': '-started',
    })
    
    rounds = rounds[0:round_limit]

    for round in rounds:

        matches = api_list(api_url + 'matches', {
            'round': round['id'],
        })

        for match in matches:

            result = match['result']
            if not result:
                continue

            categories = list(match_to_categories(match))
            for category in categories:

                bins = bins_by_category.setdefault(category, [list() for _ in length_bins])
                length = result['game_steps'] / (22.4 * 60)
                bi = max(i for i, li in enumerate(length_bins) if li <= length)
                outcome = result_to_outcome(result, category)
                if outcome != None:
                    bins[bi].append(outcome)

    intervals = {
        c: [
            (sum(b) / len(b), len(b), *proportion_confint(sum(b), len(b), alpha=confidence))
            if b else (0.5, 0, 0, 1)
            for b in bs
        ]
        for c, bs in bins_by_category.items()
    }

    return intervals
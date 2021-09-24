
import matplotlib.pyplot as plt
from plot_utils import api, api_list, api_url, winrate_intervals
import numpy as np

competition_id = 8
round_limit = 1000
confidence_alpha = 0.15
plot_args = { 'dpi': 200 }
plot_path = './publish/plot_balance'
length_bins = np.arange(0, 25, 1)

bots = api_list(api_url + 'bots')
competition = api(api_url + 'competitions/{id}'.format(id=competition_id))

bots_by_name =  {
    bot['name']: bot
    for bot in bots
}
bots_by_id =  {
    bot['id']: bot
    for bot in bots
}

def match_to_categories(match):
    result = match.get('result')
    if not result:
        return []
    race1 = bots_by_name[result['bot1_name']]['plays_race']
    race2 = bots_by_name[result['bot2_name']]['plays_race']
    matchup = { race1, race2 }
    if matchup == { 'T', 'Z' }:
        return ['TvZ']
    elif matchup == { 'T', 'P' }:
        return ['TvP']
    elif matchup == { 'Z', 'P' }:
        return ['ZvP']
    else:
        return []

def result_to_outcome(result, category):
    if result['type'] not in { 'Player1Win', 'Player2Win' }:
        return None
    winner_race = bots_by_id[result['winner']]['plays_race']
    if category == 'TvZ':
        return 1 if winner_race == 'T' else 0
    elif category == 'TvP':
        return 1 if winner_race == 'T' else 0
    elif category == 'ZvP':
        return 1 if winner_race == 'Z' else 0
    else:
        return None

legend = []
intervals_by_category = winrate_intervals(competition_id, match_to_categories, result_to_outcome, round_limit, length_bins)
for category, intervals in intervals_by_category.items():
    y, n, y_min, y_max = list(zip(*intervals))
    plt.xlabel('Game Length (min)')
    plt.ylabel('Winrate')
    legend.append('{category} (n={count})'.format(category=category, count=sum(n)))
    plt.plot(length_bins, y)
    plt.fill_between(length_bins, y_min, y_max, alpha=confidence_alpha)

plt.title('Winrate by Matchup (Season 2)')
plt.legend(legend)
plt.axhline(0.5, c='gray', linestyle='--')
plt.savefig(plot_path + '.svg', **plot_args)
plt.savefig(plot_path + '.png', **plot_args)
plt.show()
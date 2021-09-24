
from os import error
import matplotlib.pyplot as plt
from plot_utils import api, api_list, api_url, winrate_intervals
import numpy as np

DIVISION_LOWER = ('Season 2 Lower Division', 7)
DIVISION_UPPER = ('Season 2', 8)

CATEGORIES_MATCHUP = ('Matchup', True)
CATEGORIES_RACE = ('Race', False)

competition_title, competition_id = DIVISION_UPPER
categories_title, category_by_matchup = CATEGORIES_RACE
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
    if category_by_matchup:
        if race1 == race2:
            return []
        elif 'R' in { race1, race2 }:
            return []
        else:
            return ['v'.join(sorted([race1, race2]))]
    else:
        if race1 == race2:
            return []
        else:
            return [race1, race2]

def result_to_outcome(result, category):
    if result['type'] not in { 'Player1Win', 'Player2Win' }:
        return None
    if not result['winner']:
        raise Exception()
    winner_race = bots_by_id[result['winner']]['plays_race']
    if category_by_matchup:
        return 1 if winner_race == category[0] else 0
    else:
        return 1 if winner_race == category else 0

legend = []
intervals_by_category = winrate_intervals(competition_id, match_to_categories, result_to_outcome, round_limit, length_bins)
for category, intervals in sorted(intervals_by_category.items()):
    y, n, y_min, y_max = list(zip(*intervals))
    plt.xlabel('Game Length (min)')
    plt.ylabel('Winrate')
    legend.append('{category} (n={count})'.format(category=category, count=sum(n)))
    plt.plot(length_bins, y)
    plt.fill_between(length_bins, y_min, y_max, alpha=confidence_alpha)

plt.title('Winrate by {categories} ({competition})'.format(categories=categories_title, competition=competition_title))
plt.legend(legend)
plt.axhline(0.5, c='gray', linestyle='--')
plt.savefig(plot_path + '.svg', **plot_args)
plt.savefig(plot_path + '.png', **plot_args)
plt.show()
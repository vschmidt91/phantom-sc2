

import matplotlib.pyplot as plt
import numpy as np

from plot_utils import api, api_list, api_url, winrate_intervals

competition_id = 12
confidence_alpha = 0.15
bot_count = 50
plot_args = { 'dpi': 200 }
bot_filter = [
    # 'MicroMachine',
    # 'Ketroc',
    # 'Eris',
    'Rasputin',
    '12PoolBot'
]
round_limit = 100
length_bins = np.arange(0, 20, 1)

bots = {
    bot['name']:  bot
    for bot in api_list(api_url + 'bots')
}

def match_to_categories(match):
    result = match.get('result')
    if not result:
        return
    yield result['bot1_name']
    yield result['bot2_name']

def result_to_outcome(result, category):
    bot_id = bots[category]['id']
    if result['type'] != 'Player1Win' and result['type'] != 'Player2Win':
        return None
    if result['winner'] == bot_id:
        return 1
    else:
        return 0

legend = []
intervals_by_category = winrate_intervals(competition_id, match_to_categories, result_to_outcome, round_limit, length_bins)
for category, intervals in intervals_by_category.items():
    if category not in bot_filter:
        continue
    y, n, y_min, y_max = list(zip(*intervals))
    plt.xlabel('Game Length (min)')
    plt.ylabel('Winrate')
    legend.append('{category} (n={count})'.format(category=category, count=sum(n)))
    plt.plot(length_bins, y)
    plt.fill_between(length_bins, y_min, y_max, alpha=confidence_alpha)

plt.legend(legend)
plt.savefig("./publish/plot.svg", **plot_args)
plt.savefig("./publish/plot.png", **plot_args)
plt.show()
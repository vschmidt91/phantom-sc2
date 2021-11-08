
from sc2.bot_ai import BotAI

class DummyAI(BotAI):
    
    async def on_step(self, iteration: int):
        pass
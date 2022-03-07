
from .strategies.muta import Muta
from .strategies.hatch_first import HatchFirst
from .strategies.roach_rush import RoachRush
from .strategies.roach_ling_bust import RoachLingBust
from .strategies.pool12 import Pool12

OPPONENTS = {
    '71089047-c9cc-42f9-8657-8bafa0df89a0': 'negativeZero',
    '2540c0f3-238f-40a7-9c39-2e4f3dca2e2f': 'sharkbot',
    'be47253f-5e5f-4c08-af24-a705d235f021': 'whalemean',
    '944bcdff-a18f-4ed0-a5fc-35764399ef05': 'Sharkling',
    '639a757c-8901-40b6-a49f-9e804949109b': 'MechaShark	',
    '2557ad1d-ee42-4aaa-aa1b-1b46d31153d2': 'BenBotBC',
}

STRATEGIES = {
    'negativeZero': [
        # HatchFirst,
        # RoachRush,
        Muta,
        RoachLingBust,
        # Pool12,
    ],
    'BenBotBC': [
        # HatchFirst,
        RoachRush,
        # Muta,
        RoachLingBust,
        # Pool12,
    ],
    'sharkbot': [
        # HatchFirst,
        RoachRush,
        # Muta,
        RoachLingBust,
        Pool12,
    ],
    'whalemean': [
        HatchFirst,
        RoachRush,
        Muta,
        RoachLingBust,
        Pool12,
    ],
    'Sharkling': [
        HatchFirst,
        RoachRush,
        Muta,
        RoachLingBust,
        Pool12,
    ],
    'MechaShark': [
        # HatchFirst,
        RoachRush,
        # Muta,
        RoachLingBust,
        # Pool12,
    ],
}
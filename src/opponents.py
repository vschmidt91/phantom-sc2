
from .strategies.hatch_first import HatchFirst
from .strategies.pool_first import PoolFirst
from .strategies.roach_rush import RoachRush

OPPONENTS = {
    '7e234d60-12cf-46e0-ac7a-72e87f6edc53': [ # Zozo
        PoolFirst,
    ],
    'af09f69e-a162-45a8-98e8-e36c80899144': [ # Xena
        HatchFirst,
        RoachRush,
    ],
    '71089047-c9cc-42f9-8657-8bafa0df89a0': [ # negativeZero
        RoachRush,
    ],
    '5714a116-b8c8-42f5-b8dc-93b28f4adf2d': [ # spudde
        HatchFirst,
        # RoachRush,
    ]
}
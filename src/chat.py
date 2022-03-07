
GREET_MESSAGES = [
    "Who dares to challenge me?",
]

FIGHT_MESSAGES = [
    "Chicken. Chicken!",
    "Come on, then.",
    "None shall pass.",
    # "I'll do you for that!",
]

LOSS_MESSAGES = [
    "'tis but a scratch.",
    "Just a flesh wound.",
    "I'M INVINCIBLE!",
    "I've had worse",
    "Alright - we'll call it a draw.",
]

RESPONSES = {
    # "classic": "yes, yes - nothing but Zerglings",
    r"favorite .*?": "The one where the robots dominate",
    r"Now what?": "Oh, had enough, eh?",
    r"gl(\s*)hf": "I move for no bot.",
    r".*": "Then you shall die.",
}
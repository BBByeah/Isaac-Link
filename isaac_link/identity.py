import re

def player_id(value):
    value=str(value).strip().upper()
    if not re.fullmatch('[A-Z]{5}',value):raise ValueError('玩家 ID 必须是五个英文字母，例如 WHEAT。')
    return value

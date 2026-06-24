from dataclasses import dataclass, field


@dataclass
class PlayerProfile:
    name: str
    position: str
    birthdate: str
    age: int
    current_club: str
    club_id: int
    career_clubs: list[str]
    goals: int
    matches: int
    assists: int
    yellow_cards: int
    red_cards: int
    debut_year: int
    lfl_url: str
    is_free_agent: bool
    experience: str = ""
    looking: bool = False

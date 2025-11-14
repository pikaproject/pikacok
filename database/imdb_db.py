from typing import Dict, Optional

from database import dbname

imbd_db = dbname["imdb"]

DEFAULT_IMDB_LAYOUT: Dict[str, bool] = {
    "title": True,
    "duration": True,
    "category": True,
    "rating": True,
    "release": True,
    "genre": True,
    "country": True,
    "language": True,
    "cast_info": True,
    "plot": True,
    "keywords": True,
    "awards": True,
    "availability": True,
    "imdb_by": True,
    "button_open_imdb": True,
    "button_trailer": True,
}


def _merge_layout(layout: Optional[Dict[str, bool]]) -> Dict[str, bool]:
    merged = DEFAULT_IMDB_LAYOUT.copy()
    if not layout:
        return merged
    for key, value in layout.items():
        if key in merged:
            merged[key] = bool(value)
    return merged


async def is_imdbset(user_id: int) -> bool:
    user = await imbd_db.find_one({"user_id": user_id})
    if user and user.get("lang"):
        return True, user["lang"]
    return False, {}


async def add_imdbset(user_id: int, lang):
    await imbd_db.update_one(
        {"user_id": user_id}, {"$set": {"lang": lang}}, upsert=True
    )


async def remove_imdbset(user_id: int):
    user = await imbd_db.find_one({"user_id": user_id})
    if user:
        return await imbd_db.delete_one({"user_id": user_id})


async def get_imdb_layout(user_id: int) -> Dict[str, bool]:
    user = await imbd_db.find_one({"user_id": user_id})
    return _merge_layout((user or {}).get("layout"))


async def set_imdb_layout(user_id: int, layout: Dict[str, bool]) -> Dict[str, bool]:
    merged = _merge_layout(layout)
    await imbd_db.update_one(
        {"user_id": user_id},
        {"$set": {"layout": merged}, "$setOnInsert": {"lang": "eng"}},
        upsert=True,
    )
    return merged


async def toggle_imdb_layout(user_id: int, field: str) -> Dict[str, bool]:
    if field not in DEFAULT_IMDB_LAYOUT:
        raise KeyError(f"Unknown layout field: {field}")
    layout = await get_imdb_layout(user_id)
    layout[field] = not layout[field]
    await imbd_db.update_one(
        {"user_id": user_id},
        {
            "$set": {f"layout.{field}": layout[field]},
            "$setOnInsert": {"lang": "eng"},
        },
        upsert=True,
    )
    return layout


async def reset_imdb_layout(user_id: int) -> Dict[str, bool]:
    defaults = DEFAULT_IMDB_LAYOUT.copy()
    await imbd_db.update_one(
        {"user_id": user_id},
        {"$set": {"layout": defaults}, "$setOnInsert": {"lang": "eng"}},
        upsert=True,
    )
    return defaults


async def set_custom_imdb_template(user_id: int, template: str) -> None:
    await imbd_db.update_one(
        {"user_id": user_id},
        {
            "$set": {"custom_layout": template},
            "$setOnInsert": {"lang": "eng", "layout": DEFAULT_IMDB_LAYOUT.copy()},
        },
        upsert=True,
    )


async def get_custom_imdb_template(user_id: int) -> Optional[str]:
    user = await imbd_db.find_one(
        {"user_id": user_id}, {"custom_layout": 1, "_id": 0}
    )
    return (user or {}).get("custom_layout")


async def clear_custom_imdb_template(user_id: int) -> None:
    await imbd_db.update_one(
        {"user_id": user_id},
        {"$unset": {"custom_layout": ""}},
    )

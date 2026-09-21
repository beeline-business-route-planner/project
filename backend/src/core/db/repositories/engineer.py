from src.core.db.dto import EngineerCreateDTO
from src.core.db.models import Engineer, EngineerSkill
from src.core.db.repositories.base import BaseRepository


class EngineerRepository(BaseRepository[Engineer]):
    model = Engineer

    def add_many(self, engineers: list[EngineerCreateDTO]) -> None:
        for engineer in engineers:
            model = Engineer()
            model.upload_id = engineer.upload_id
            model.name = engineer.name
            model.region = engineer.region
            model.start_point_address = engineer.start_point_address
            model.start_point_latitude = engineer.start_point_latitude
            model.start_point_longitude = engineer.start_point_longitude
            model.shift_start = engineer.shift_start
            model.shift_end = engineer.shift_end
            model.skills = []
            for skill in engineer.skills:
                engineer_skill = EngineerSkill()
                engineer_skill.skill = skill
                model.skills.append(engineer_skill)
            model.vehicle_type = engineer.vehicle_type
            self.add(model)

from datetime import datetime
from typing import Optional, Any

from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTable
from sqlalchemy import Column, Integer, ForeignKey, DateTime, String, text, Float, Boolean
from sqlalchemy.ext.asyncio import async_object_session as object_session, AsyncSession
from sqlalchemy.orm import relationship

import config
from app import database, sessions, definition
from app.constants.formulas import bancho_formula, dict_id2obj
from app.constants.privacy import Privacy
from app.constants.privileges import MemberPosition
from app.constants.servers import Server
from app.database import Base, db_session, async_session_maker
from app.definition import Raw, AstChecker
from app.logging import log, Ansi


class UserAccount(Base):
    __tablename__ = "user_accounts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), index=True, nullable=False)
    server_id = Column(Integer, nullable=False)
    server_user_id = Column(Integer, nullable=False)
    server_user_name = Column(String(64), nullable=False)
    checked_at = Column(DateTime(True), nullable=False, server_default=text("now()"))


class User(SQLAlchemyBaseUserTable[int], Base):
    __tablename__ = "users"

    id = Column(Integer, nullable=False, autoincrement=True, primary_key=True)
    username = Column(String(64), nullable=False, unique=True)
    privileges = Column(Integer, nullable=False, default=1)
    country = Column(String(64), nullable=False)
    created_at = Column(DateTime(True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(True), nullable=False, server_default=text("now()"))
    active_team_id = Column(Integer, ForeignKey('teams.id'), nullable=True)

    accounts = relationship('UserAccount', lazy='selectin', uselist=True)
    active_team = relationship('Team', lazy='selectin', uselist=False)
    teams = relationship('TeamMember', lazy='dynamic', back_populates="member", uselist=True)

    @property
    def active_stage(self) -> Optional['Stage']:
        team = self.active_team
        return team.active_stage if team else None


class Beatmap(Base):
    __tablename__ = "beatmaps"
    md5 = Column(String(64), primary_key=True)
    id = Column(Integer, nullable=True, index=True)  # null if beatmap is on local server
    set_id = Column(Integer, nullable=True)  # null if beatmap is on local server
    ranked_status = Column(Integer, nullable=False)
    artist = Column(String(64), nullable=False)
    title = Column(String(64), nullable=False)
    version = Column(String(64), nullable=False)
    creator = Column(String(64), nullable=False)
    filename = Column(String(64), nullable=False)
    total_length = Column(Integer, nullable=False)
    max_combo = Column(Integer, nullable=False)
    mode = Column(Integer, nullable=False)
    bpm = Column(Float, nullable=False)
    cs = Column(Float, nullable=False)
    ar = Column(Float, nullable=False)
    od = Column(Float, nullable=False)
    hp = Column(Float, nullable=False)
    star_rating = Column(Float, nullable=False)
    updated_at = Column(DateTime(True), nullable=False, server_default=text("now()"))
    server_updated_at = Column(DateTime(True), nullable=False)
    server_id = Column(Integer, nullable=False, default=Server.BANCHO)

    @staticmethod
    async def _save_response(session: AsyncSession, response_data: list[dict[str, Any]]):
        for entry in response_data:
            filename = (
                "{artist} - {title} ({creator}) [{version}].osu"
                .format(**entry)
                .translate(definition.IGNORED_BEATMAP_CHARS)
            )

            _last_update = entry["last_update"]
            last_update = datetime(
                year=int(_last_update[0:4]),
                month=int(_last_update[5:7]),
                day=int(_last_update[8:10]),
                hour=int(_last_update[11:13]),
                minute=int(_last_update[14:16]),
                second=int(_last_update[17:19]),
            )

            beatmap = Beatmap(
                md5=entry["file_md5"],
                id=entry["beatmap_id"],
                set_id=entry["beatmapset_id"],
                ranked_status=entry["approved"],
                artist=entry["artist"],
                title=entry["title"],
                version=entry["version"],
                creator=entry["creator"],
                filename=filename,
                total_length=int(entry["total_length"]),
                max_combo=int(entry["max_combo"]),
                mode=int(entry["mode"]),
                bpm=float(entry["bpm"] if entry["bpm"] is not None else 0),
                cs=float(entry["diff_size"]),
                od=float(entry["diff_overall"]),
                ar=float(entry["diff_approach"]),
                hp=float(entry["diff_drain"]),
                star_rating=float(entry["difficultyrating"]),
                server_updated_at=last_update
            )

            await database.add_model(session, beatmap)

    @staticmethod
    async def request_api(ident: str) -> Optional['Beatmap']:
        params = {}

        if definition.MD5_PATTERN.match(ident):
            params['md5'] = ident
        if ident.isnumeric():
            params['id'] = int(ident)

        if config.debug:
            log(f"Doing api (getbeatmaps) request {params}", Ansi.LMAGENTA)
        if config.osu_api_v1_key != "":
            url = "https://old.ppy.sh/api/get_beatmaps"
            params["k"] = str(config.osu_api_v1_key)
        else:
            url = "https://osu.direct/api/get_beatmaps"

        async with sessions.http_client.get(url, params=params) as response:
            response_data = await response.json()
            if response.status == 200 and response_data:
                session: AsyncSession = await async_session_maker()
                await Beatmap._save_response(session, response_data)
                if params['id']:
                    return await Beatmap.from_id(session, params['id'])
                if params['md5']:
                    return await Beatmap.from_md5(session, params['md5'])

    @staticmethod
    async def from_id(session: AsyncSession, beatmap_id: int) -> Optional['Beatmap']:
        return await database.select_model(session, Beatmap, Beatmap.id == beatmap_id)

    @staticmethod
    async def from_md5(session: AsyncSession, md5: str) -> Optional['Beatmap']:
        return await database.get_model(session, md5, Beatmap)


class Score(Base):
    __tablename__ = 'scores'

    score_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    beatmap_md5 = Column(String(64), ForeignKey('beatmaps.md5'), nullable=False, index=True)
    score = Column(Integer, nullable=False)
    performance_points = Column(Float, nullable=False)
    accuracy = Column(Float, nullable=False)
    highest_combo = Column(Integer, nullable=False)
    full_combo = Column(Boolean, nullable=False)
    mods = Column(Integer, nullable=False)
    num_300s = Column(Integer, nullable=False)
    num_100s = Column(Integer, nullable=False)
    num_50s = Column(Integer, nullable=False)
    num_misses = Column(Integer, nullable=False)
    num_gekis = Column(Integer, nullable=False)
    num_katus = Column(Integer, nullable=False)
    grade = Column(String(64), nullable=False)
    mode = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime(True), nullable=False, server_default=text("now()"))
    server_id = Column(Integer, nullable=False, default=Server.LOCAL)
    stage_id = Column(Integer, ForeignKey('stages.id'), index=True, nullable=False)

    beatmap = relationship('Beatmap', lazy='selectin')
    stage = relationship('Stage', lazy='selectin', back_populates='scores')

    @staticmethod
    async def from_id(session: AsyncSession, score_id: int) -> Optional['Score']:
        return await database.get_model(session, score_id, Score)

    @staticmethod
    def from_web(info: dict, stage: 'Stage') -> Raw['Score']:
        pp = dict_id2obj[stage.formula].calculate(mode=stage.mode)  # TODO: provide correct args to calculate pp
        score = Score(**info, stage_id=stage.id, performance_points=pp)
        return Raw['Score'](score)

    async def submit_raw(self, session: AsyncSession, condition: str) -> Optional['Score']:
        variables = {
            "acc": self.accuracy,
            "max_combo": self.highest_combo,
            "mods": self.mods,
            "score": self.score
        }
        if AstChecker(condition).check(variables):
            return await database.add_model(session, self)


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False)
    privacy = Column(Integer, nullable=False, default=Privacy.PROTECTED)
    achieved = Column(Boolean, nullable=False, default=False)
    create_at = Column(DateTime(True), nullable=False, server_default=text("now()"))
    finish_at = Column(DateTime(True), nullable=True)
    active_stage_id = Column(Integer, ForeignKey('stages.id'), nullable=True)

    active_stage = relationship('Stage', lazy='selectin', foreign_keys='Team.active_stage_id')
    member = relationship('TeamMember', lazy='dynamic', back_populates="teams")
    stages = relationship('Stage', lazy='dynamic', foreign_keys='Stage.team_id')

    async def position_of(self, user_id: int) -> MemberPosition:
        session = object_session(self)
        team = await session.scalar(self.team)
        member = await database.query_model(session, team.users, User.id == user_id)
        if member is None:
            return MemberPosition.EMPTY
        return MemberPosition.MEMBER  # TODO: from association


class Stage(Base):
    __tablename__ = "stages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False)
    mode = Column(Integer, nullable=False, default=0)
    formula = Column(Integer, nullable=False, default=bancho_formula.formula_id)
    created_at = Column(DateTime(True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(True), nullable=False, server_default=text("now()"))
    pool_id = Column(Integer, ForeignKey('pools.id'), nullable=False)
    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)

    pool = relationship('Pool', lazy='selectin')  # originated from which pool
    team = relationship('Team', lazy='selectin', foreign_keys='Stage.team_id',
                        viewonly=True)  # which team owned the stage
    scores = relationship('Score', lazy='dynamic', uselist=True, back_populates='stage')
    maps = relationship('StageMap', lazy='dynamic', uselist=True)

    @staticmethod
    async def from_id(session: AsyncSession, stage_id: int) -> Optional['Stage']:
        return await session.get(Stage, stage_id)

    async def get_map(self, beatmap_md5: str) -> Optional['StageMap']:
        session = object_session(self)
        return await database.query_model(session, self.maps, StageMap.map_md5 == beatmap_md5)


class Pool(Base):
    __tablename__ = "pools"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False)
    description = Column(String(64), nullable=True)
    mode = Column(Integer, nullable=False)
    privacy = Column(Integer, nullable=False, default=Privacy.PUBLIC)
    created_at = Column(DateTime(True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(True), nullable=False, server_default=text("now()"))
    creator_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    creator = relationship('User', lazy='selectin')
    maps = relationship('PoolMap', lazy='dynamic', uselist=True)


class PoolMap(Base):
    __tablename__ = "pool_maps"
    id = Column(Integer, primary_key=True, autoincrement=True)
    pool_id = Column(Integer, ForeignKey('pools.id'), index=True, nullable=False)
    map_md5 = Column(String(64), ForeignKey('beatmaps.md5'), index=True, nullable=False)
    description = Column(String(64), nullable=False)
    condition_ast = Column(String(64), nullable=False)
    condition_name = Column(String(64), nullable=False)
    condition_represent_mods = Column(Integer, nullable=False)

    beatmap = relationship('Beatmap', lazy='selectin')


class StageMap(Base):
    __tablename__ = "stage_maps"
    id = Column(Integer, primary_key=True, autoincrement=True)
    stage_id = Column(Integer, ForeignKey('stages.id'), index=True, nullable=False)
    map_md5 = Column(String(64), ForeignKey('beatmaps.md5'), index=True, nullable=False)
    description = Column(String(64), nullable=False)
    condition_ast = Column(String(64), nullable=False)
    condition_name = Column(String(64), nullable=False)
    condition_represent_mods = Column(Integer, nullable=False)

    beatmap = relationship('Beatmap', lazy='selectin')


class TeamMember(Base):
    __tablename__ = "team_member"
    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(Integer, ForeignKey('teams.id'), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), index=True, nullable=False)
    member_position = Column(Integer, nullable=False, default=MemberPosition.MEMBER)

    teams = relationship("Team", back_populates="member")
    member = relationship("User", back_populates="teams")

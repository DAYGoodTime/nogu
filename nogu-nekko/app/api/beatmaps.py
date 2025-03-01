from fastapi import APIRouter, Depends
from sse_starlette import EventSourceResponse
from starlette.requests import Request

import config
from app.api.schemas import APIResponse, docs, ModelResponse
from app.api.schemas.beatmap import BeatmapBase, BeatmapEvent
from app.api.users import current_user
from app.database import db_session as database_session
from app.definition import Operator
from app.interaction import Beatmap, User
from app.logging import log, Ansi


class BeatmapRequestOperator(Operator):
    async def operate(self, session: str, args: str) -> ModelResponse:
        async with database_session() as db_session:
            beatmap = await Beatmap.from_ident(db_session, args)
            if beatmap is not None:
                self.skip_next_interval = True
            if beatmap is None:
                beatmap = await Beatmap.request_api(args)
            if beatmap is None:
                return ModelResponse(identifier=args, status='failure')
            return ModelResponse(identifier=args, status='success', data=BeatmapBase.from_orm(beatmap))


router = APIRouter(prefix='/beatmaps', tags=['beatmaps'])
beatmap_request_operator = BeatmapRequestOperator(interval=config.beatmap_requests_interval)


@router.get('/{ident}', responses=docs(BeatmapBase))
async def get_beatmap(ident: str):
    async with database_session() as session:
        beatmap = await Beatmap.from_ident(session, ident)
        if beatmap is None:
            return APIResponse(success=False, info="Beatmap not found.")
        return APIResponse(beatmap=BeatmapBase.from_orm(beatmap))


@router.post('/stream/', responses=docs(BeatmapEvent))
async def stream_beatmap(request: Request, idents: list[str], user: User = Depends(current_user)):
    log(f"Doing beatmap streaming: {user.username} ({str(len(idents))} maps)", Ansi.LYELLOW)
    for ident in idents:
        await beatmap_request_operator.new_operation(str(user.id), ident)
    return EventSourceResponse(beatmap_request_operator.event_generator(request, str(user.id)))

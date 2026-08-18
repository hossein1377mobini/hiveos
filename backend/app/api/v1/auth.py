"""US-003 auth endpoints (v1): OTP send / resend / verify."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas import OtpSendRequest, OtpSendResponse, OtpVerifyRequest, OtpVerifyResponse
from app.services import otp_service

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/auth/send-otp",
    response_model=OtpSendResponse,
    status_code=status.HTTP_200_OK,
    operation_id="sendOtp",
    tags=["Onboarding"],
)
async def send_otp(data: OtpSendRequest, session: DbSession) -> OtpSendResponse:
    return await otp_service.send_otp(session, data.phone)


@router.post(
    "/auth/resend-otp",
    response_model=OtpSendResponse,
    status_code=status.HTTP_200_OK,
    operation_id="resendOtp",
    tags=["Onboarding"],
)
async def resend_otp(data: OtpSendRequest, session: DbSession) -> OtpSendResponse:
    return await otp_service.resend_otp(session, data.phone)


@router.post(
    "/auth/verify-otp",
    response_model=OtpVerifyResponse,
    status_code=status.HTTP_200_OK,
    operation_id="verifyOtp",
    tags=["Onboarding"],
)
async def verify_otp(data: OtpVerifyRequest, session: DbSession) -> OtpVerifyResponse:
    return await otp_service.verify_otp(session, data.phone, data.code)

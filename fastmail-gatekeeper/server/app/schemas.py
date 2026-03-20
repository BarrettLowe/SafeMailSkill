from typing import Any

from pydantic import BaseModel, EmailStr, field_validator


class DeleteRequest(BaseModel):
    message_id: str


class SendRequest(BaseModel):
    to: EmailStr
    subject: str
    body: str


class ApproveRequest(BaseModel):
    pin: str

    @field_validator("pin")
    @classmethod
    def pin_must_be_four_digits(cls, v: str) -> str:
        if not v.isdigit() or len(v) != 4:
            raise ValueError("PIN must be exactly 4 digits")
        return v


class JMAPProxyRequest(BaseModel):
    methodCalls: list[list[Any]]

    @field_validator("methodCalls")
    @classmethod
    def validate_method_calls(cls, v: list) -> list:
        if not v:
            raise ValueError("methodCalls cannot be empty")
        for i, call in enumerate(v):
            if not isinstance(call, list) or len(call) != 3:
                raise ValueError(
                    f"methodCalls[{i}] must be a 3-element array "
                    "[method_name, args_object, call_id]"
                )
            if not isinstance(call[0], str):
                raise ValueError(f"methodCalls[{i}][0] (method name) must be a string")
            if not isinstance(call[1], dict):
                raise ValueError(f"methodCalls[{i}][1] (args) must be an object")
            if not isinstance(call[2], str):
                raise ValueError(f"methodCalls[{i}][2] (callId) must be a string")
        return v

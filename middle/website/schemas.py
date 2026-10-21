from typing import Literal
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WASTE = {'general':'一般垃圾','glass':'玻璃','food_waste':'廚餘','other_recycling':'其他回收'}
RESIDUAL = {'none':'無殘留','food':'食物殘留','liquid':'液體殘留','not_assessable':'不適用／無法判斷'}

def canonical(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9]{4,20}',value,flags=re.ASCII):
        raise ValueError('ID 僅限 ASCII 英文字母與數字，長度 4～20，不可有空格或符號')
    return value.lower()

class UserIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id: str
    nickname: str = Field(min_length=1,max_length=40)
    _canonical=field_validator('id')(canonical)

    @field_validator('nickname')
    @classmethod
    def nickname_valid(cls,value):
        value=value.strip()
        if not value or any(ord(c)<32 for c in value):raise ValueError('暱稱不可空白或包含控制字元')
        return value

class Annotation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    waste: Literal['general','glass','food_waste','other_recycling'] | None = None
    residual: Literal['none','food','liquid','not_assessable'] | None = None
    waste_confirmed: bool = False
    residual_confirmed: bool = False

    @model_validator(mode='after')
    def validate_confirmation(self):
        if self.waste in ('general','food_waste') and self.residual not in (None,'not_assessable'):
            raise ValueError('依本專題物品範圍，一般垃圾／廚餘的人工殘留答案僅允許未填或不適用')
        if self.waste_confirmed and self.waste is None:raise ValueError('垃圾答案尚未選擇，不能標為已確認')
        if self.residual_confirmed and self.residual is None:raise ValueError('殘留答案尚未選擇，不能標為已確認')
        return self

class UploadMeta(BaseModel):
    model_config=ConfigDict(extra='forbid')
    user_id: str
    mode: Literal['general','evaluation']
    request_key: str = Field(pattern=r'^[a-fA-F0-9-]{36}$')
    annotations: list[Annotation] = Field(default_factory=list,max_length=20)
    _canonical=field_validator('user_id')(canonical)

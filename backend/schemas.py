from pydantic import BaseModel
from typing import Optional


class StudentDataBase(BaseModel):
    year: int
    course: int
    admission: int
    transfers_in: int
    expelled: int
    academic_leave: int
    restored: int


class StudentDataCreate(StudentDataBase):
    pass


class StudentDataResponse(StudentDataBase):
    id: int

    class Config:
        from_attributes = True

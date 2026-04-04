from typing import Optional
import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Unicode,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Actions(Base):
    __tablename__ = "Actions"
    __table_args__ = (
        PrimaryKeyConstraint("action_id", name="PK__Actions__74EFC217613776DF"),
        Index("UQ__Actions__7B1DA93E403577E8", "action_name", unique=True),
    )

    action_id: Mapped[int] = mapped_column(
        Integer, Identity(start=1, increment=1), primary_key=True
    )
    action_name: Mapped[str] = mapped_column(
        String(50, "SQL_Latin1_General_CP1_CI_AS"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(
        String(20, "SQL_Latin1_General_CP1_CI_AS"), nullable=False
    )

    Role_Actions: Mapped[list["RoleActions"]] = relationship(
        "RoleActions", back_populates="action"
    )
    Individual_Permissions: Mapped[list["IndividualPermissions"]] = relationship(
        "IndividualPermissions", back_populates="action"
    )


class Roles(Base):
    __tablename__ = "Roles"
    __table_args__ = (
        PrimaryKeyConstraint("role_id", name="PK__Roles__760965CCC09EDA46"),
        Index("UQ__Roles__783254B15DA7ED1D", "role_name", unique=True),
    )

    role_id: Mapped[int] = mapped_column(Integer, Identity(start=1, increment=1), primary_key=True)
    role_name: Mapped[str] = mapped_column(Unicode(50, 'SQL_Latin1_General_CP1_CI_AS'), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Unicode(255, 'SQL_Latin1_General_CP1_CI_AS'))

    Role_Actions: Mapped[list['RoleActions']] = relationship('RoleActions', back_populates='role')
    Users: Mapped[list['Users']] = relationship('Users', back_populates='role')


class VirtualPaths(Base):
    __tablename__ = 'Virtual_Paths'
    __table_args__ = (
        PrimaryKeyConstraint('path_id', name='PK_Virtual_Paths'),
        Index('UQ_Virtual_Paths_FullPath', 'full_path', unique=True)
    )

    path_id: Mapped[int] = mapped_column(Integer, Identity(start=1, increment=1), primary_key=True)
    full_path: Mapped[str] = mapped_column(Unicode(500, 'SQL_Latin1_General_CP1_CI_AS'), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('(getdate())'))
    description: Mapped[Optional[str]] = mapped_column(Unicode(collation='SQL_Latin1_General_CP1_CI_AS'))
    depth: Mapped[int] = mapped_column(Integer, nullable=False)

    Documents: Mapped[list['Documents']] = relationship('Documents', back_populates='path')


class Sysdiagrams(Base):
    __tablename__ = 'sysdiagrams'
    __table_args__ = (
        PrimaryKeyConstraint('diagram_id', name='PK__sysdiagr__C2B05B6116CEA0A5'),
        Index('UK_principal_name', 'principal_id', 'name', unique=True)
    )

    Role_Actions: Mapped[list["RoleActions"]] = relationship(
        "RoleActions", back_populates="role"
    )
    Users: Mapped[list["Users"]] = relationship("Users", back_populates="role")


class RoleActions(Base):
    __tablename__ = "Role_Actions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["action_id"], ["Actions.action_id"], name="FK_RoleActions_Action"
        ),
        ForeignKeyConstraint(
            ["role_id"], ["Roles.role_id"], name="FK_RoleActions_Role"
        ),
        PrimaryKeyConstraint("role_action_id", name="PK__Role_Act__61564664385A28CE"),
        Index("UQ_RoleAction", "role_id", "action_id", unique=True),
    )

    role_action_id: Mapped[int] = mapped_column(
        BigInteger, Identity(start=1, increment=1), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action_id: Mapped[int] = mapped_column(Integer, nullable=False)

    action: Mapped["Actions"] = relationship("Actions", back_populates="Role_Actions")
    role: Mapped["Roles"] = relationship("Roles", back_populates="Role_Actions")


class Users(Base):
    __tablename__ = "Users"
    __table_args__ = (
        ForeignKeyConstraint(["role_id"], ["Roles.role_id"], name="FK_Users_Roles"),
        PrimaryKeyConstraint("user_id", name="PK__Users__B9BE370F5FB662F3"),
        Index("UQ__Users__AB6E61646BFAE4C2", "email", unique=True),
        Index("UQ__Users__F3DBC57265EB5883", "username", unique=True),
    )

    user_id: Mapped[int] = mapped_column(
        Integer, Identity(start=1, increment=1), primary_key=True
    )
    username: Mapped[str] = mapped_column(
        Unicode(50, "SQL_Latin1_General_CP1_CI_AS"), nullable=False
    )
    full_name: Mapped[str] = mapped_column(
        Unicode(100, "SQL_Latin1_General_CP1_CI_AS"), nullable=False
    )
    email: Mapped[str] = mapped_column(
        Unicode(100, "SQL_Latin1_General_CP1_CI_AS"), nullable=False
    )
    password_hash: Mapped[str] = mapped_column(
        String(255, "SQL_Latin1_General_CP1_CI_AS"), nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("(getdate())")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("((0))")
    )
    role_id: Mapped[Optional[int]] = mapped_column(
        Integer, server_default=text("((1))")
    )

    role: Mapped[Optional['Roles']] = relationship('Roles', back_populates='Users')
    Documents: Mapped[list['Documents']] = relationship('Documents', back_populates='uploaded_by_user')
    Individual_Permissions: Mapped[list['IndividualPermissions']] = relationship('IndividualPermissions', back_populates='user')
    Logs: Mapped[list['Logs']] = relationship('Logs', back_populates='user')


class Documents(Base):
    __tablename__ = 'Documents'
    __table_args__ = (
        ForeignKeyConstraint(['path_id'], ['Virtual_Paths.path_id'], name='FK_Doc_Path'),
        ForeignKeyConstraint(['uploaded_by_user_id'], ['Users.user_id'], name='FK_Doc_Uploader'),
        PrimaryKeyConstraint('doc_id', name='PK__Document__8AD02924828124C8'),
        Index('UQ_Documents_Filename_Path', 'filename', 'path_id', unique=True)
    )

    doc_id: Mapped[int] = mapped_column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    filename: Mapped[str] = mapped_column(Unicode(255, 'SQL_Latin1_General_CP1_CI_AS'), nullable=False)
    path_id: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    mongo_doc_id: Mapped[str] = mapped_column(String(36, 'SQL_Latin1_General_CP1_CI_AS'), nullable=False)
    uploaded_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('(getdate())'))

    path: Mapped['VirtualPaths'] = relationship('VirtualPaths', back_populates='Documents')
    uploaded_by_user: Mapped['Users'] = relationship('Users', back_populates='Documents')
    Processing_Status: Mapped[list['ProcessingStatus']] = relationship('ProcessingStatus', back_populates='doc')


class IndividualPermissions(Base):
    __tablename__ = "Individual_Permissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["action_id"], ["Actions.action_id"], name="FK_IndPerm_Action"
        ),
        ForeignKeyConstraint(["user_id"], ["Users.user_id"], name="FK_IndPerm_User"),
        PrimaryKeyConstraint("permission_id", name="PK__Individu__E5331AFA5F875CCF"),
    )

    permission_id: Mapped[int] = mapped_column(
        BigInteger, Identity(start=1, increment=1), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action_id: Mapped[int] = mapped_column(Integer, nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entity_type: Mapped[str] = mapped_column(
        String(20, "SQL_Latin1_General_CP1_CI_AS"), nullable=False
    )
    is_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_inherited: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("((0))")
    )

    action: Mapped["Actions"] = relationship(
        "Actions", back_populates="Individual_Permissions"
    )
    user: Mapped["Users"] = relationship(
        "Users", back_populates="Individual_Permissions"
    )


class Logs(Base):
    __tablename__ = "Logs"
    __table_args__ = (
        ForeignKeyConstraint(["user_id"], ["Users.user_id"], name="FK_Log_User"),
        PrimaryKeyConstraint("log_id", name="PK__Logs__9E2397E0BA6DA292"),
    )

    log_id: Mapped[int] = mapped_column(
        BigInteger, Identity(start=1, increment=1), primary_key=True
    )
    log_timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("(getdate())")
    )
    action_type: Mapped[str] = mapped_column(
        String(50, "SQL_Latin1_General_CP1_CI_AS"), nullable=False
    )
    user_id: Mapped[Optional[int]] = mapped_column(Integer)
    entity_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    details: Mapped[Optional[str]] = mapped_column(
        Unicode(collation="SQL_Latin1_General_CP1_CI_AS")
    )

    user: Mapped[Optional["Users"]] = relationship("Users", back_populates="Logs")


class ProcessingStatus(Base):
    __tablename__ = "Processing_Status"
    __table_args__ = (
        ForeignKeyConstraint(
            ["doc_id"], ["Documents.doc_id"], name="FK_ProcStatus_Doc"
        ),
        PrimaryKeyConstraint("status_id", name="PK__Processi__3683B5310CA4907C"),
    )

    status_id: Mapped[int] = mapped_column(
        BigInteger, Identity(start=1, increment=1), primary_key=True
    )
    doc_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    stage_name: Mapped[str] = mapped_column(
        String(50, "SQL_Latin1_General_CP1_CI_AS"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20, "SQL_Latin1_General_CP1_CI_AS"), nullable=False
    )
    start_time: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("(getdate())")
    )
    end_time: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    error_message: Mapped[Optional[str]] = mapped_column(
        Unicode(collation="SQL_Latin1_General_CP1_CI_AS")
    )

    doc: Mapped["Documents"] = relationship(
        "Documents", back_populates="Processing_Status"
    )

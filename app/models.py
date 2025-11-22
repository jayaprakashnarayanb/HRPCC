# app/models.py
from sqlalchemy import Column, Integer, String, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from .db import Base


class Policy(Base):
    __tablename__ = "policies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    raw_text = Column(Text)

    # "leave" | "benefit" | "both"
    scope = Column(String, default="both")

    rules = relationship("Rule", back_populates="policy", cascade="all, delete-orphan")


class Rule(Base):
    __tablename__ = "rules"

    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(Integer, ForeignKey("policies.id"))

    rule_code = Column(String, index=True)
    description = Column(Text)
    category = Column(String)      # "leave" | "benefit"
    severity = Column(String)      # "low" | "medium" | "high"
    check_type = Column(String)    # e.g. leave_advance_days, benefit_max_amount, ...
    params = Column(JSON)          # rule-specific params

    # Supported check_type values in this MVP:
    # - "leave_advance_days"
    # - "benefit_max_amount"
    # - "benefit_requires_receipt"
    # - "benefit_allowed_types"

    policy = relationship("Policy", back_populates="rules")


class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(Text, nullable=True)

    # "leave" or "benefit"
    dataset_type = Column(String, index=True)

    file_path = Column(String)  # path to CSV file


class Violation(Base):
    __tablename__ = "violations"

    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(Integer, ForeignKey("policies.id"))
    rule_id = Column(Integer, ForeignKey("rules.id"))
    dataset_id = Column(Integer, ForeignKey("datasets.id"))

    employee_identifier = Column(String)
    evidence = Column(Text)
    risk = Column(String)
    explanation = Column(Text, nullable=True)

    policy = relationship("Policy")
    rule = relationship("Rule")
    dataset = relationship("Dataset")


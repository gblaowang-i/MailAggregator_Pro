import json
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_api_token
from app.core.database import get_db
from app.models.email import EmailAccount
from app.models.email import EmailRecord
from app.models.mail_rule import MailRule
from app.schemas.accounts import MailRuleCreate, MailRuleOut, MailRuleUpdate

router = APIRouter(
    prefix="/rules",
    tags=["rules"],
    dependencies=[Depends(verify_api_token)],
)


@router.get("/", response_model=List[MailRuleOut])
async def list_rules(
    db: AsyncSession = Depends(get_db),
) -> list[MailRule]:
    result = await db.execute(
        select(MailRule).order_by(MailRule.rule_order, MailRule.id)
    )
    return list(result.scalars().all())


@router.post(
    "/",
    response_model=MailRuleOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_rule(
    payload: MailRuleCreate,
    db: AsyncSession = Depends(get_db),
) -> MailRule:
    if payload.account_id is not None:
        acc = await db.get(EmailAccount, payload.account_id)
        if not acc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="account_id not found",
            )
    rule = MailRule(
        name=payload.name or "",
        rule_order=payload.rule_order,
        account_id=payload.account_id,
        sender_pattern=(payload.sender_pattern or "").strip() or None,
        subject_pattern=(payload.subject_pattern or "").strip() or None,
        body_pattern=(payload.body_pattern or "").strip() or None,
        add_labels=json.dumps(payload.add_labels or [], ensure_ascii=False),
        push_telegram=payload.push_telegram,
        mark_read=payload.mark_read,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.patch("/{rule_id}", response_model=MailRuleOut)
async def update_rule(
    rule_id: int,
    payload: MailRuleUpdate,
    db: AsyncSession = Depends(get_db),
) -> MailRule:
    rule = await db.get(MailRule, rule_id)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if payload.name is not None:
        rule.name = payload.name
    if payload.rule_order is not None:
        rule.rule_order = payload.rule_order
    if "account_id" in payload.dict(exclude_unset=True):
        if payload.account_id is not None:
            acc = await db.get(EmailAccount, payload.account_id)
            if not acc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="account_id not found",
                )
        rule.account_id = payload.account_id
    if payload.sender_pattern is not None:
        rule.sender_pattern = payload.sender_pattern.strip() or None
    if payload.subject_pattern is not None:
        rule.subject_pattern = payload.subject_pattern.strip() or None
    if payload.body_pattern is not None:
        rule.body_pattern = payload.body_pattern.strip() or None
    if payload.add_labels is not None:
        rule.add_labels = json.dumps(payload.add_labels, ensure_ascii=False)
    if payload.push_telegram is not None:
        rule.push_telegram = payload.push_telegram
    if payload.mark_read is not None:
        rule.mark_read = payload.mark_read
    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    rule = await db.get(MailRule, rule_id)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    # 删除规则时，清理该规则独有的标签（保留仍被其他规则使用的标签），并限定在规则适用账号范围内。
    deleted_account_id = rule.account_id
    labels_to_remove: list[str] = []
    try:
        labels_to_remove = json.loads(rule.add_labels) if rule.add_labels else []
        if not isinstance(labels_to_remove, list):
            labels_to_remove = []
        labels_to_remove = [str(x).strip() for x in labels_to_remove if str(x).strip()]
    except Exception:
        labels_to_remove = []

    await db.delete(rule)
    await db.commit()

    if not labels_to_remove:
        return

    # Exclude labels still referenced by any remaining rule.
    rem_res = await db.execute(select(MailRule))
    remaining_labels: set[str] = set()
    for rem_rule in rem_res.scalars().all():
        try:
            rem_lbs = json.loads(rem_rule.add_labels) if rem_rule.add_labels else []
            if isinstance(rem_lbs, list):
                for lb in rem_lbs:
                    if isinstance(lb, str) and lb.strip():
                        remaining_labels.add(lb.strip())
        except Exception:
            continue

    remove_set = set(labels_to_remove) - remaining_labels
    if not remove_set:
        return

    stmt = select(EmailRecord)
    if deleted_account_id is not None:
        stmt = stmt.where(EmailRecord.account_id == deleted_account_id)
    res = await db.execute(stmt)
    records = list(res.scalars().all())
    changed = 0
    for rec in records:
        if not rec.labels:
            continue
        try:
            labels = json.loads(rec.labels) if rec.labels.strip() else []
        except Exception:
            continue
        if not isinstance(labels, list) or not labels:
            continue
        next_labels = [lb for lb in labels if str(lb) not in remove_set]
        if next_labels != labels:
            rec.labels = json.dumps(next_labels, ensure_ascii=False)
            changed += 1
    if changed:
        await db.commit()


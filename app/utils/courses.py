_INTERVAL_LABELS = {
    "weekly": "Weekly", "monthly": "Monthly",
    "quarterly": "Quarterly", "yearly": "Yearly",
}


def _build_payment_types(course) -> list:
    """
    Return every active billing option for a course as a list of dicts.
    Fee > 0 is the sole gate — no separate boolean flag required.
 
    Shape of each entry:
        { payment_type, fee, label, subscription_interval?, access_period_days?,
          installment_count?, installment_fee? }
    """
    pt       = getattr(course, "payment_type", None) or "one_time"
    base_fee = float(getattr(course, "fee", None) or 0)
    sub_fee  = float(getattr(course, "subscription_fee",  None) or 0)
    payg_fee = float(getattr(course, "pay_as_you_go_fee", None) or 0)
    inst_fee = float(getattr(course, "installment_fee",   None) or 0)
    inst_cnt = getattr(course, "installment_count", None)
 
    # Free path
    if pt == "free" or (base_fee == 0 and sub_fee == 0 and payg_fee == 0 and inst_fee == 0):
        return [{"payment_type": "free", "fee": 0, "label": "Free",
                 "subscription_interval": None, "access_period_days": None}]
 
    options = []
 
    if base_fee > 0:
        options.append({
            "payment_type": "one_time", "fee": base_fee, "label": "One-time",
            "subscription_interval": None, "access_period_days": None,
        })
 
    if sub_fee > 0:
        interval = (getattr(course, "subscription_interval", None) or "monthly").lower()
        options.append({
            "payment_type": "subscription", "fee": sub_fee,
            "label": _INTERVAL_LABELS.get(interval, "Subscription"),
            "subscription_interval": interval, "access_period_days": None,
        })
 
    if payg_fee > 0:
        access_days = int(getattr(course, "access_period_days", None) or 30)
        options.append({
            "payment_type": "pay_as_you_go", "fee": payg_fee, "label": "Pay-as-you-go",
            "subscription_interval": None, "access_period_days": access_days,
        })
 
    if inst_fee > 0 and inst_cnt and inst_cnt > 1:
        options.append({
            "payment_type": "installment", "fee": inst_fee,
            "label": f"{inst_cnt}× instalments",
            "installment_count": inst_cnt, "installment_fee": inst_fee,
            "subscription_interval": None, "access_period_days": None,
        })
 
    if not options:
        options.append({
            "payment_type": pt, "fee": base_fee,
            "label": {"one_time": "One-time"}.get(pt, pt),
            "subscription_interval": None, "access_period_days": None,
        })
 
    return options


def _pricing_fields(course) -> dict:
    """
    Returns the pricing-related fields that every course endpoint should include.
    Spread this into your existing return dict:
 
        return {
            "id": course.id,
            "title": course.title,
            ...existing fields...,
            **_pricing_fields(course),    # ← add this line
        }
    """
    return {
        "fee":                   float(getattr(course, "fee", 0) or 0),
        "payment_type":          getattr(course, "payment_type", "one_time"),
        "subscription_fee":      float(course.subscription_fee  or 0) if getattr(course, "subscription_fee",  None) is not None else None,
        "subscription_enabled":  bool(getattr(course, "subscription_enabled",  False)),
        "subscription_interval": getattr(course, "subscription_interval", "monthly") or "monthly",
        "pay_as_you_go_fee":     float(course.pay_as_you_go_fee or 0) if getattr(course, "pay_as_you_go_fee", None) is not None else None,
        "pay_as_you_go_enabled": bool(getattr(course, "pay_as_you_go_enabled", False)),
        "access_period_days":    int(getattr(course, "access_period_days", 30) or 30),
        "installment_enabled":   bool(getattr(course, "installment_enabled",   False)),
        "installment_count":     getattr(course, "installment_count",   None),
        "installment_fee":       float(course.installment_fee or 0) if getattr(course, "installment_fee", None) is not None else None,
        "instructor_led_fee":    float(getattr(course, "instructor_led_fee", 0) or 0),
        "throttle_enabled":      bool(getattr(course, "throttle_enabled",     False)),
        "weekly_topic_limit":    getattr(course, "weekly_topic_limit",  None),
        "monthly_topic_limit":   getattr(course, "monthly_topic_limit", None),
        "available_payment_types": _build_payment_types(course),
    }


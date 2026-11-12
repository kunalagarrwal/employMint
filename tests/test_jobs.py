"""Visa and pay detection on job descriptions."""
import jobs as J


def blocked(text):
    return set(J.visa_flags(text)) & J.VISA_BLOCKING


def test_no_sponsorship_detected():
    assert "no_sponsorship" in blocked("Please note we will not sponsor visas for this role.")


def test_us_citizenship_detected():
    assert blocked("Applicants must be U.S. citizens due to government contract requirements.")


def test_eeo_boilerplate_is_not_a_block():
    assert not blocked("All qualified applicants will receive consideration without regard to citizenship status.")


def test_pay_hourly():
    pay = J.pay_from_text("The hourly pay for this internship is $57/hr.")
    assert pay and "57" in pay and pay.endswith("/hr")


def test_funding_round_is_not_pay():
    assert J.pay_from_text("We raised a $30M Series A led by top investors.") is None


def test_sponsorship_signal():
    assert J.sponsorship_signal("Students on CPT are welcome to apply.", {})[0] == "cpt"

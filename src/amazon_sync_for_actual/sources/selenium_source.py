"""Experimental Selenium scraper for Amazon order data.

Kept for backwards compatibility with the original project.  Prefer the CSV
source: Amazon actively blocks automation, frequently changes its markup and may
require CAPTCHAs, so this path is inherently fragile.

Updated for Selenium 4 (the original used the removed ``find_element_by_*`` API
and the old ``Chrome()`` constructor).  ``selenium`` and ``pyotp`` are imported
lazily so importing this module never requires them.
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional

from .base import AmazonSource
from .invoice_html import parse_invoice
from ..models import AmazonOrder

log = logging.getLogger(__name__)

__all__ = ["SeleniumSource"]

_ORDER_HISTORY = (
    "https://www.amazon.com/gp/your-account/order-history"
    "?ie=UTF8&orderFilter=months-6&startIndex={start}"
)
_INVOICE = (
    "https://www.amazon.com/gp/css/summary/print.html/"
    "?ie=UTF8&orderID={order_id}"
)


class SeleniumSource(AmazonSource):
    def __init__(
        self,
        email: Optional[str],
        password: Optional[str],
        otp_secret: Optional[str] = None,
        pages: int = 3,
        headless: bool = True,
    ):
        if not email or not password:
            raise ValueError("SeleniumSource requires an Amazon email and password.")
        self.email = email
        self.password = password
        self.otp_secret = otp_secret
        self.pages = pages
        self.headless = headless
        self._driver = None

    # -- driver lifecycle --------------------------------------------------
    def _build_driver(self):
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "The selenium extra is required for source=selenium. Install it "
                "with `pip install amazon-sync-for-actual[selenium]`."
            ) from exc

        options = Options()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        # Selenium >= 4.6 ships Selenium Manager, which resolves the driver
        # automatically -- no webdriver-manager needed.
        return webdriver.Chrome(options=options)

    def _ensure_driver(self):
        if self._driver is None:
            self._driver = self._build_driver()
            self._sign_in()
        return self._driver

    def close(self) -> None:
        if self._driver is not None:
            try:
                self._driver.quit()
            finally:
                self._driver = None

    # -- scraping ----------------------------------------------------------
    def _sign_in(self) -> None:
        from selenium.webdriver.common.by import By

        driver = self._driver
        driver.get("https://www.amazon.com/ap/signin")
        time.sleep(2)

        driver.find_element(By.ID, "ap_email").send_keys(self.email)
        driver.find_element(By.ID, "continue").click()
        time.sleep(1)
        driver.find_element(By.ID, "ap_password").send_keys(self.password)
        driver.find_element(By.ID, "signInSubmit").click()
        time.sleep(2)

        if self.otp_secret:
            self._submit_otp(driver, By)

    def _submit_otp(self, driver, By) -> None:
        import pyotp

        code = pyotp.TOTP(self.otp_secret).now()
        for field_id in ("auth-mfa-otpcode", "input-box-otp"):
            try:
                field = driver.find_element(By.ID, field_id)
            except Exception:  # noqa: BLE001 - selenium raises many element errors
                continue
            field.send_keys(code)
            for button_id in ("auth-signin-button", "auth-mfa-submit"):
                try:
                    driver.find_element(By.ID, button_id).click()
                    break
                except Exception:  # noqa: BLE001
                    continue
            time.sleep(2)
            return

    def _order_ids(self, driver) -> List[str]:
        from bs4 import BeautifulSoup

        ids: List[str] = []
        for page in range(self.pages):
            driver.get(_ORDER_HISTORY.format(start=page * 10))
            time.sleep(1)
            soup = BeautifulSoup(driver.page_source, "html.parser")
            for node in soup.find_all("bdi"):
                text = node.get_text().strip()
                if text and text not in ids:
                    ids.append(text)
        return ids

    def fetch_orders(self) -> List[AmazonOrder]:
        driver = self._ensure_driver()
        try:
            orders: List[AmazonOrder] = []
            for order_id in self._order_ids(driver):
                driver.get(_INVOICE.format(order_id=order_id))
                time.sleep(1)
                order = parse_invoice(driver.page_source, order_id=order_id)
                if order is not None and order.items:
                    orders.append(order)
            log.info("Scraped %d order(s) via Selenium", len(orders))
            return orders
        finally:
            self.close()

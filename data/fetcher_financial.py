#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetcher_financial.py
====================

Thu thập dữ liệu Fundamental Analysis (FA) từ Vnstock - source KBS.

TRIẾT LÝ CỦA FILE NÀY
---------------------
    DATA ACCURACY > DATA COMPLETENESS > CODE CONVENIENCE

Cụ thể:

1.  KHÔNG có bước nào biến đổi giá trị số lấy từ API.
    Không nhân 100, không chia 1000, không "normalize percentage".
    Giá trị ghi vào JSON == giá trị raw của KBS (chỉ làm tròn 2 chữ số).

2.  Ngoại lệ duy nhất: 3 trường growth (eps_growth_qoq, eps_growth_yoy,
    revenue_growth_qoq) được TỰ TÍNH từ raw EPS / raw revenue của
    income_statement(), theo công thức đã thống nhất ở mục 10 của spec.

3.  Mỗi metric có đúng một nguồn:

        eps          <- income_statement() row  earnings_per_share_vnd
        revenue      <- income_statement() row  revenue (chọn row tường minh)
        pe           <- ratio()            row  pe_ratio
        pb           <- ratio()            row  pb_ratio
        roe          <- ratio()            row  roe            (KHÔNG roe_trailling)
        debt_equity  <- ratio()            row  debt_to_equity
        net_margin   <- ratio()            row  net_margin

    trailing_eps KHÔNG BAO GIỜ được dùng làm EPS quý.

4.  Join income <-> ratio theo KỲ (dict lookup), không bao giờ theo vị trí cột.

5.  Cột duplicate dạng "2025-Q4_1" bị BỎ QUA mặc định
    (ALLOW_SUFFIXED_COLUMNS = False). Không bao giờ ghi đè cột chính.

6.  Growth chỉ được tính khi kỳ đối chiếu là quý LIỀN KỀ thật sự
    (hoặc cùng quý năm trước thật sự). Không có dữ liệu -> None -> null.

7.  Giá trị đáng ngờ chỉ được GHI LOG, không bao giờ bị tự sửa.
    Xem data/fa_diagnostics.json sau mỗi lần chạy.

GIỚI HẠN ĐÃ BIẾT CỦA NGUỒN (xem thêm phần LIMITATIONS cuối file)
----------------------------------------------------------------
-   Vnstock Community Edition: "Financial statements limited to 4 periods."
    => EPS YoY theo quý gần như luôn = null. Đây là null HỢP LỆ.
-   sector KHÔNG được suy đoán. Chỉ lấy từ symbols.csv.

PHIÊN BẢN 2 - BỔ SUNG revenue / net_profit / cfo (KHÔNG có free_float_pct)
--------------------------------------------------------------------------
Theo yêu cầu bổ sung của nhóm (net_profit theo quý, revenue theo năm,
cfo/cfo_ttm), file này giờ dùng THÊM một nguồn thứ hai:

    vnfinancialdata (package do giảng viên publish, gọi tắt "vnf")

CHỈ dùng vnf cho hai việc, đã xác minh bằng chính output test của nhóm:

    revenue     <- income_statement, item_code "is_doanh_so_thuan"
                   (Doanh số THUẦN - đúng khái niệm "doanh thu thuần" nhóm
                   đã dùng cho KBS. KHÔNG dùng "is_doanh_so" - đó là doanh
                   số GỘP, sai khái niệm.)
    net_profit  <- income_statement, item_code
                   "is_loi_nhuan_cua_co_dong_cua_cong_ty_me"
                   (cùng khái niệm "lợi nhuận cổ đông công ty mẹ" như
                   profit_after_tax_for_shareholders_of_parent_company
                   bên KBS - hai nguồn nói cùng một thứ.)
    cfo         <- cash_flow, item_code
                   "cf_luu_chuyen_tien_thuan_tu_cac_hoat_dong_san_xuat_kinh_doanh"
                   (Lưu chuyển tiền THUẦN từ HĐ SXKD = CFO đúng định nghĩa.
                   KHÔNG dùng "cf_luu_chuyen_tien_thuan_trong_ky" - đó là
                   dòng tiền thuần TOÀN BỘ kỳ, gồm cả đầu tư + tài chính,
                   SAI metric.)

GIỚI HẠN ĐÃ BIẾT của vnf (từ chính log test của nhóm):

    - CHỈ hỗ trợ HSX, HNX. UPCOM KHÔNG được hỗ trợ
      ("Unsupported exchange: UPCOM"). Với UPCOM, code cào bù bằng
      income_statement(year) của KBS - CHỈ khi không có dữ liệu quý,
      và CHỈ khi vượt qua kiểm tra chống đảo nhãn kỳ (xem
      ALLOW_INCOME_YEAR_REVERSAL_CORRECTION bên dưới).
    - KHÔNG có tham số quý ('period'/'frequency'/'type' đều bị từ chối).
      => revenue/net_profit/cfo theo QUÝ vẫn phải lấy từ KBS
         (income_statement(quarter), vốn đã có sẵn trong pipeline).
    - KHÔNG có free_float. Trường free_float_pct đã bị LOẠI KHỎI schema
      theo yêu cầu, vì endpoint SSI Fiin được đề xuất trả 403 (bị chặn),
      và nhóm quyết định không tiếp tục dò tìm nguồn khác ở phiên bản này.
    - Tên cột chứa GIÁ TRỊ trong DataFrame của vnf CHƯA được xác nhận
      (script kiểm tra của nhóm chỉ in ra item_code/item_name, không in
      cột giá trị). Code dò một danh sách ngắn tên cột khả dĩ ("value",
      "Value", "gia_tri") và LOG RÕ nếu không tìm thấy, thay vì đoán.

cfo_ttm: KHÔNG được triển khai trong bản này (luôn null), vì tính TTM
đúng nghĩa cần cộng dồn 4 quý CFO liên tiếp, mà hiện KHÔNG có nguồn CFO
theo quý đáng tin cậy. Trường này để sẵn trong schema cho tương lai.

QUYẾT ĐỊNH KIẾN TRÚC QUAN TRỌNG (đọc trước khi đổi hành vi):

    Với ticker CÓ dữ liệu quý hợp lệ từ KBS (đa số mã thanh khoản), code
    sẽ THÊM các dòng "20XX-Năm" (revenue/net_profit/cfo từ vnf, các field
    khác để null) vào CUỐI history, bên cạnh các dòng quý - KHÔNG thay thế
    dữ liệu quý. Việc này không tốn thêm lệnh gọi KBS nào (vnf được tải
    bulk MỘT LẦN cho cả HSX/HNX, không phải theo từng ticker), nên không
    ảnh hưởng rate limit. Đây LÀ một thay đổi so với kiến trúc "quý HOẶC
    năm" trước đó - lý do: nếu không làm vậy, yêu cầu "revenue theo năm"
    sẽ không bao giờ xuất hiện cho phần lớn các mã có dữ liệu quý tốt.
    history được sắp xếp lại theo thời gian sau khi gộp.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

try:
    from vnstock import Finance
except ImportError:  # pragma: no cover
    Finance = None

try:
    import vnfinancialdata as _vnf
except ImportError:  # pragma: no cover
    _vnf = None


# ==============================================================
# CẤU HÌNH
# ==============================================================

SOURCE = "KBS"

# BẮT BUỘC trong giai đoạn test. Chỉ đổi sau khi output được xác nhận.
LIMIT = 5

# Số kỳ ghi vào history của mỗi ticker.
MAX_PERIODS = 4

# Có chấp nhận cột duplicate kiểu "2025-Q4_1" khi KHÔNG tồn tại cột
# chính "2025-Q4" hay không.
#
# False = an toàn. Cột _1 trong thực tế đã được quan sát là bản sao giá trị
# của MỘT KỲ KHÁC (PNJ: 2025-Q4_1 == 2026-Q2). Dùng nó = gán dữ liệu kỳ này
# cho kỳ khác, vi phạm nguyên tắc số 6 của spec.
ALLOW_SUFFIXED_COLUMNS = False

DEFAULT_SECTOR = "Chưa phân loại"

# Nguồn EPS cho kỳ NĂM: "ratio" | "income"
#
# Mặc định "ratio" dựa trên bằng chứng số học từ lần chạy test 5 mã:
#
#   GVT, giá ngụ ý = EPS x PE (phải cùng bậc độ lớn qua các năm):
#       ratio(year)        -> 99,059 / 71,410 / 86,009 / 84,868   spread 1.39x
#       income(year)/1000  -> 135,724 / 167,423 / 36,683 / 61,921 spread 4.56x
#
#   Dãy EPS của income(year) là dãy của ratio(year) ĐẢO NGƯỢC thứ tự.
#   => nhãn năm của income_statement(period="year") KHÔNG khớp kỳ với PE/PB/ROE.
#
# Đây là kết luận từ 2 mã (GVT, MGC), chưa phải chân lý. Cơ chế
# ANNUAL_EPS_CONFLICT bên dưới sẽ cảnh báo mỗi khi hai nguồn bất đồng,
# nên nếu giả định này sai ở mã khác, bạn sẽ thấy ngay trong diagnostics.
ANNUAL_EPS_SOURCE = "ratio"

# Ngưỡng cảnh báo lệch kỳ theo giá ngụ ý (EPS x PE) cho kỳ NĂM.
IMPLIED_PRICE_SPREAD_THRESHOLD = 3.0

# --------------------------------------------------------------
# Cấu hình nguồn vnfinancialdata (revenue / net_profit / cfo NĂM)
# --------------------------------------------------------------

# Sàn được vnfinancialdata hỗ trợ - đã xác nhận bằng test thực tế của nhóm.
# UPCOM KHÔNG có trong danh sách này (API trả "Unsupported exchange").
VNF_EXCHANGES: Tuple[str, ...] = ("HSX", "HNX")

# item_code đã xác nhận từ log liệt kê chỉ tiêu của nhóm - KHÔNG suy đoán.
VNF_ITEM_REVENUE = "is_doanh_so_thuan"                # Doanh số THUẦN
VNF_ITEM_NET_PROFIT = "is_loi_nhuan_cua_co_dong_cua_cong_ty_me"
VNF_ITEM_CFO = "cf_luu_chuyen_tien_thuan_tu_cac_hoat_dong_san_xuat_kinh_doanh"

# Tên cột KHẢ DĨ chứa giá trị số trong DataFrame của vnf - CHƯA được xác
# nhận bằng tài liệu/response thật. Nếu không cột nào khớp, log rõ và bỏ
# qua nguồn đó (không đoán đại một cột).
VNF_VALUE_COLUMN_CANDIDATES: Tuple[str, ...] = ("value", "Value", "VALUE",
                                                "gia_tri")

# Khi phát hiện income_statement(year) của KBS bị ĐẢO NHÃN KỲ (xem
# check_margin_alignment / INCOME_PERIODS_REVERSED), có tự động sửa nhãn
# hay không.
#
# Mặc định False: dữ liệu bị null thay vì bị đảo tự động, vì việc đảo dựa
# trên suy luận thống kê (dù bằng chứng khá mạnh với GVT/MGC), không phải
# xác nhận từ tài liệu API - đúng tinh thần "không suy đoán" của spec.
# Chỉ bật cờ này sau khi tự kiểm chứng thêm với --debug-raw trên nhiều mã.
ALLOW_INCOME_YEAR_REVERSAL_CORRECTION = True


# ==============================================================
# ĐỊNH DANH ROW (item_id) - so khớp EXACT, case-insensitive
# ==============================================================

RATIO_ROW_IDS: Dict[str, Tuple[str, ...]] = {
    "pe": ("pe_ratio",),
    "pb": ("pb_ratio",),
    # KHÔNG thêm "roe_trailling" vào đây. Đó là metric khác.
    "roe": ("roe",),
    "debt_equity": ("debt_to_equity", "debtperequity"),
    "net_margin": ("net_margin",),
}

# EPS năm: nếu income_statement(year) không có, mới fallback sang ratio(year).
RATIO_YEAR_EPS_IDS: Tuple[str, ...] = (
    "earning_per_share",
    "eps",
    "trailing_eps",
)

INCOME_EPS_IDS: Tuple[str, ...] = (
    "earnings_per_share_vnd",
    "earning_per_share",
    "eps",
)

INCOME_REVENUE_ID = "revenue"

# Lợi nhuận TOÀN công ty (bao gồm cả lợi ích cổ đông thiểu số).
# CHỈ dùng để đối chiếu với net_margin của ratio() khi lợi nhuận cổ đông
# công ty mẹ (INCOME_PROFIT_IDS) không khớp - xem
# check_margin_alignment_with_fallback. KHÔNG BAO GIỜ dùng làm giá trị
# xuất ra field "net_profit" - field đó luôn là lợi nhuận cổ đông công ty
# mẹ, đúng convention của nhóm và đúng định nghĩa vnfinancialdata
# (is_loi_nhuan_cua_co_dong_cua_cong_ty_me).
#
# Phát hiện từ VID (có lợi ích cổ đông thiểu số ~0.57 tỷ ở 2026-Q2):
# net_margin của ratio() khớp TUYỆT ĐỐI khi tính bằng lợi nhuận TOÀN công
# ty / revenue, không khớp khi dùng lợi nhuận cổ đông công ty mẹ. Với mã
# không có cổ đông thiểu số (PNJ, SWC), hai định nghĩa trùng nhau nên
# không lộ ra khác biệt này.
INCOME_TOTAL_PROFIT_IDS: Tuple[str, ...] = ("net_profit",)

# Dùng cho phép kiểm chứng profit/revenue == net_margin (không ghi vào JSON).
INCOME_PROFIT_IDS: Tuple[str, ...] = (
    "profit_after_tax_for_shareholders_of_parent_company",
    "profit_after_tax_for_shareholders_of_the_parent_company",
    "profit_after_tax",
)

# Khi item_id = "revenue" có nhiều row, ưu tiên row có label chứa các từ này.
REVENUE_LABEL_PREFERENCE: Tuple[str, ...] = (
    "doanh thu thuần",
    "net revenue",
    "doanh thu thuan",
)

METADATA_COLUMNS = {
    "item",
    "item_en",
    "item_id",
    "ticker",
    "symbol",
    "index",
    "yearreport",
    "lengthreport",
}

QUARTER_COL_RE = re.compile(r"^(\d{4})-Q([1-4])$")
YEAR_COL_RE = re.compile(r"^(\d{4})(?:-Năm|-Nam|-Year)?$")
SUFFIX_RE = re.compile(r"^(?P<base>.+?)_(?P<n>\d+)$")


# ==============================================================
# LOGGING
# ==============================================================

logger = logging.getLogger("fa_fetcher")


def setup_logging(log_path: str = "data/fa_fetch.log") -> None:
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console)

    directory = os.path.dirname(log_path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    logger.addHandler(file_handler)


# ==============================================================
# PERIOD - kiểu kỳ chuẩn hoá nội bộ
# ==============================================================

class Period:
    """
    Kỳ chuẩn hoá.

        kind = "quarter" -> (year, quarter)   -> "2026-Q2"
        kind = "year"    -> (year, None)      -> "2025-Năm"

    Chỉ có MỘT nơi sinh ra chuỗi period ghi vào JSON: Period.label().
    Nhờ vậy không thể tái diễn lỗi "2022-Năm-Năm".
    """

    __slots__ = ("kind", "year", "quarter")

    def __init__(self, kind: str, year: int, quarter: Optional[int] = None):
        self.kind = kind
        self.year = year
        self.quarter = quarter

    # ---------- factory ----------

    @staticmethod
    def parse(text: str, kind: str) -> Optional["Period"]:
        text = str(text).strip()

        if kind == "quarter":
            match = QUARTER_COL_RE.match(text)
            if not match:
                return None
            return Period("quarter", int(match.group(1)), int(match.group(2)))

        match = YEAR_COL_RE.match(text)
        if not match:
            return None
        return Period("year", int(match.group(1)))

    # ---------- identity ----------

    def key(self) -> Tuple[int, int]:
        """Khoá sắp xếp theo thời gian."""
        return (self.year, self.quarter or 0)

    def label(self) -> str:
        if self.kind == "quarter":
            return f"{self.year}-Q{self.quarter}"
        return f"{self.year}-Năm"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Period) and self.key() == other.key() \
            and self.kind == other.kind

    def __hash__(self) -> int:
        return hash((self.kind, self.year, self.quarter))

    def __repr__(self) -> str:  # pragma: no cover
        return f"Period({self.label()})"

    # ---------- quan hệ thời gian ----------

    def previous_quarter(self) -> Optional["Period"]:
        if self.kind != "quarter" or self.quarter is None:
            return None
        if self.quarter > 1:
            return Period("quarter", self.year, self.quarter - 1)
        return Period("quarter", self.year - 1, 4)

    def previous_year_same_quarter(self) -> Optional["Period"]:
        if self.kind == "quarter":
            return Period("quarter", self.year - 1, self.quarter)
        return Period("year", self.year - 1)


def parse_period_label(label: Any) -> Optional[Period]:
    """
    Chuyển một chuỗi period trong JSON (ví dụ "2026-Q2" hoặc "2025-Năm")
    ngược lại thành Period. Dùng để sắp xếp/validate history sau khi GỘP
    dòng quý và dòng năm (mục PHIÊN BẢN 2 trong docstring đầu file).
    """
    if not isinstance(label, str):
        return None
    if QUARTER_COL_RE.match(label):
        return Period.parse(label, "quarter")
    if label.endswith("-Năm"):
        return Period.parse(label[: -len("-Năm")], "year")
    return None


# ==============================================================
# DIAGNOSTICS
# ==============================================================

class Diagnostics:
    """
    Gom mọi cảnh báo theo ticker. Ghi ra data/fa_diagnostics.json.

    Diagnostics KHÔNG BAO GIỜ làm thay đổi giá trị dữ liệu.
    Nó chỉ mô tả những gì đã quan sát được.
    """

    def __init__(self) -> None:
        self._items: Dict[str, List[Dict[str, Any]]] = {}

    def add(
        self,
        ticker: str,
        code: str,
        message: str,
        period: Optional[str] = None,
        level: str = "WARNING",
    ) -> None:
        self._items.setdefault(ticker, []).append(
            {
                "level": level,
                "code": code,
                "period": period,
                "message": message,
            }
        )
        prefix = f"  [{level}] {ticker}"
        if period:
            prefix += f" {period}"
        logger.warning(f"{prefix}: {message}")

    def note(self, ticker: str, code: str, message: str,
             period: Optional[str] = None) -> None:
        """Ghi nhận thông tin, không phải cảnh báo. Không in ra console."""
        self._items.setdefault(ticker, []).append(
            {
                "level": "INFO",
                "code": code,
                "period": period,
                "message": message,
            }
        )
        logger.debug(f"  [INFO] {ticker} {period or ''}: {message}")

    def for_ticker(self, ticker: str) -> List[Dict[str, Any]]:
        return self._items.get(ticker, [])

    def as_dict(self) -> Dict[str, List[Dict[str, Any]]]:
        return self._items

    def merge_into(self, existing: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(existing)
        merged.update(self._items)
        return merged


# ==============================================================
# DATAFRAME HELPERS
# ==============================================================

def flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    vnstock đôi khi trả MultiIndex columns. Làm phẳng về chuỗi.
    Không đổi dữ liệu, chỉ đổi nhãn cột.
    """
    if df is None or df.empty:
        return df

    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [
            "_".join(str(part) for part in col if str(part) != "nan").strip("_")
            for col in df.columns
        ]
    return df


def safe_float(value: Any) -> Optional[float]:
    """
    Chuyển về float. KHÔNG scale, KHÔNG đoán.
    Giá trị thiếu / không parse được -> None.
    """
    if value is None:
        return None

    try:
        if isinstance(value, float) and pd.isna(value):
            return None
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if text in ("", "-", "--", "N/A", "n/a", "nan", "NaN", "None", "null"):
        return None

    # Chỉ bỏ dấu phân cách nghìn. Không đụng tới dấu %.
    text = text.replace(",", "")

    if text.endswith("%"):
        # Nếu API trả chuỗi có "%", đó là thông tin về unit -> giữ nguyên số
        # và để caller biết qua diagnostics. Ở đây chỉ strip ký tự.
        text = text[:-1].strip()

    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def round_or_none(value: Optional[float], digits: int = 2) -> Optional[float]:
    if value is None:
        return None
    try:
        result = round(float(value), digits)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    if result in (float("inf"), float("-inf")):
        return None
    return result


# ==============================================================
# PERIOD RESOLVER
# ==============================================================

class PeriodResolver:
    """
    Ánh xạ: Period  ->  tên cột trong DataFrame.

    Quy tắc (mục 5 + 20 của spec):

        - Cột chính ("2025-Q4") LUÔN được ưu tiên.
        - Cột duplicate ("2025-Q4_1") mặc định bị BỎ.
        - Nếu tồn tại cả hai, so sánh giá trị và ghi diagnostics khi khác nhau.
        - Không bao giờ để duplicate ghi đè cột chính.
    """

    def __init__(self, diagnostics: Diagnostics, ticker: str):
        self.diag = diagnostics
        self.ticker = ticker

    def resolve(
        self,
        df: pd.DataFrame,
        kind: str,
        df_name: str,
    ) -> Dict[Period, str]:

        if df is None or df.empty:
            return {}

        exact: Dict[Period, str] = {}
        suffixed: Dict[Period, List[str]] = {}

        for raw_col in df.columns:
            col = str(raw_col).strip()

            if col.lower() in METADATA_COLUMNS:
                continue

            suffix_match = SUFFIX_RE.match(col)
            base = suffix_match.group("base") if suffix_match else col

            period = Period.parse(base, kind)
            if period is None:
                continue

            if suffix_match:
                suffixed.setdefault(period, []).append(col)
            else:
                if period in exact:
                    # Hai cột cùng tên chính xác - bất thường.
                    self.diag.add(
                        self.ticker,
                        "DUPLICATE_EXACT_COLUMN",
                        f"{df_name}: kỳ {period.label()} xuất hiện ở nhiều cột "
                        f"chính ({exact[period]}, {col}). Giữ cột đầu tiên.",
                        period.label(),
                    )
                    continue
                exact[period] = col

        # -- đối chiếu duplicate với cột chính --------------------
        for period, columns in suffixed.items():
            if period in exact:
                for col in columns:
                    self._compare_duplicate(df, df_name, period,
                                            exact[period], col)
                continue

            if ALLOW_SUFFIXED_COLUMNS:
                exact[period] = columns[0]
                self.diag.add(
                    self.ticker,
                    "SUFFIXED_COLUMN_USED",
                    f"{df_name}: kỳ {period.label()} CHỈ có cột duplicate "
                    f"{columns[0]}. Đang dùng nó (ALLOW_SUFFIXED_COLUMNS=True). "
                    f"Giá trị có thể thuộc kỳ khác.",
                    period.label(),
                )
            else:
                self.diag.add(
                    self.ticker,
                    "SUFFIXED_COLUMN_SKIPPED",
                    f"{df_name}: bỏ qua cột duplicate {columns[0]} vì không có "
                    f"cột chính {period.label()}. Metric của kỳ này sẽ là null.",
                    period.label(),
                )

        return exact

    def _compare_duplicate(
        self,
        df: pd.DataFrame,
        df_name: str,
        period: Period,
        main_col: str,
        dup_col: str,
    ) -> None:
        """
        So sánh cột chính và cột _1. Chỉ ghi log, không dùng cột _1.
        Đây chính là cơ chế phát hiện lỗi PNJ: 2025-Q4_1 == 2026-Q2.
        """
        try:
            main_series = df[main_col]
            dup_series = df[dup_col]
            identical = main_series.equals(dup_series)
        except Exception:
            identical = False

        if identical:
            self.diag.note(
                self.ticker,
                "DUPLICATE_COLUMN_IDENTICAL",
                f"{df_name}: cột {dup_col} trùng hệt {main_col}. Đã bỏ qua.",
                period.label(),
            )
        else:
            self.diag.add(
                self.ticker,
                "DUPLICATE_COLUMN_CONFLICT",
                f"{df_name}: cột {dup_col} KHÁC cột chính {main_col}. "
                f"Chỉ dùng {main_col}. Cần kiểm tra raw KBS.",
                period.label(),
            )


# ==============================================================
# ROW RESOLVER
# ==============================================================

class RowResolver:
    """
    Tìm chỉ số dòng theo item_id (exact, case-insensitive).

    Không dùng str.contains cho ratio() vì "roe" contains sẽ bắt luôn
    "roe_trailling".
    """

    def __init__(self, diagnostics: Diagnostics, ticker: str):
        self.diag = diagnostics
        self.ticker = ticker

    def find_all_by_item_id(
        self,
        df: pd.DataFrame,
        item_id: str,
    ) -> List[Any]:
        if df is None or df.empty or "item_id" not in df.columns:
            return []

        normalized = df["item_id"].astype(str).str.strip().str.lower()
        return df.index[normalized == item_id.strip().lower()].tolist()

    def find_one(
        self,
        df: pd.DataFrame,
        item_ids: Sequence[str],
        metric_name: str,
        df_name: str,
    ) -> Optional[Any]:
        """
        Trả về index dòng đầu tiên khớp EXACT một trong các item_ids.
        Nếu một item_id khớp nhiều dòng -> ghi cảnh báo (mơ hồ).
        """
        if df is None or df.empty or "item_id" not in df.columns:
            return None

        for item_id in item_ids:
            matches = self.find_all_by_item_id(df, item_id)
            if not matches:
                continue

            if len(matches) > 1:
                labels = self._labels(df, matches)
                self.diag.add(
                    self.ticker,
                    "AMBIGUOUS_ROW",
                    f"{df_name}: item_id='{item_id}' cho metric "
                    f"{metric_name} khớp {len(matches)} dòng {labels}. "
                    f"Dùng dòng đầu tiên.",
                )
            return matches[0]

        return None

    def find_revenue_row(
        self,
        df: pd.DataFrame,
        df_name: str,
    ) -> Optional[Any]:
        """
        income_statement có thể có nhiều dòng item_id='revenue'.
        Chọn TƯỜNG MINH dòng doanh thu thuần, và log dòng đã chọn.
        """
        if df is None or df.empty or "item_id" not in df.columns:
            return None

        matches = self.find_all_by_item_id(df, INCOME_REVENUE_ID)
        if not matches:
            return None

        if len(matches) == 1:
            self.diag.note(
                self.ticker,
                "REVENUE_ROW",
                f"{df_name}: dùng dòng revenue "
                f"'{self._label(df, matches[0])}'.",
            )
            return matches[0]

        if "item" in df.columns:
            for keyword in REVENUE_LABEL_PREFERENCE:
                for index in matches:
                    label = str(df.loc[index, "item"]).strip().lower()
                    if keyword in label:
                        self.diag.note(
                            self.ticker,
                            "REVENUE_ROW",
                            f"{df_name}: có {len(matches)} dòng revenue "
                            f"{self._labels(df, matches)}. Chọn "
                            f"'{self._label(df, index)}' theo từ khoá "
                            f"'{keyword}'.",
                        )
                        return index

        self.diag.add(
            self.ticker,
            "REVENUE_ROW_AMBIGUOUS",
            f"{df_name}: có {len(matches)} dòng item_id='revenue' "
            f"{self._labels(df, matches)} nhưng không dòng nào khớp nhãn "
            f"'doanh thu thuần'. revenue_growth_qoq sẽ để null.",
        )
        return None

    # ---------- nhãn để log ----------

    @staticmethod
    def _label(df: pd.DataFrame, index: Any) -> str:
        if "item" in df.columns:
            return str(df.loc[index, "item"]).strip()
        return str(index)

    @classmethod
    def _labels(cls, df: pd.DataFrame, indices: Sequence[Any]) -> str:
        return "[" + ", ".join(f"'{cls._label(df, i)}'" for i in indices) + "]"


def get_cell(
    df: pd.DataFrame,
    row_index: Optional[Any],
    column: Optional[str],
) -> Optional[float]:
    """Lấy đúng một ô. Thiếu row hoặc thiếu column -> None."""
    if df is None or df.empty or row_index is None or column is None:
        return None
    if column not in df.columns:
        return None

    try:
        value = df.loc[row_index, column]
    except Exception:
        return None

    if isinstance(value, pd.Series):
        value = value.iloc[0]

    return safe_float(value)


# ==============================================================
# GROWTH
# ==============================================================

def calc_growth(
    current: Optional[float],
    previous: Optional[float],
) -> Optional[float]:
    """
    (current - previous) / abs(previous) * 100

    previous = 0 hoặc thiếu -> None (mục 10 của spec).
    Mẫu số dùng abs() theo thống nhất của nhóm.
    """
    if current is None or previous is None:
        return None
    if previous == 0:
        return None
    return (current - previous) / abs(previous) * 100.0


# ==============================================================
# SUSPICION DETECTOR - CHỈ LOG, KHÔNG SỬA
# ==============================================================

class SuspicionDetector:
    """
    Phát hiện giá trị đáng ngờ để bạn đi kiểm tra raw KBS.

    KHÔNG có hàm nào ở đây thay đổi dữ liệu.
    """

    def __init__(self, diagnostics: Diagnostics, ticker: str):
        self.diag = diagnostics
        self.ticker = ticker

    def check_row(self, period_label: str, row: Dict[str, Any]) -> None:
        pe = row.get("pe")
        pb = row.get("pb")
        roe = row.get("roe")
        debt_equity = row.get("debt_equity")
        net_margin = row.get("net_margin")

        if pe is not None and pe == 0:
            self.diag.add(self.ticker, "SUSPICIOUS_PE",
                          "pe = 0. KBS có thể đang trả placeholder thay vì "
                          "giá trị thật. Giữ nguyên raw.", period_label)
        if pe is not None and pe > 500:
            self.diag.add(self.ticker, "SUSPICIOUS_PE",
                          f"pe = {pe} rất cao (EPS gần 0?). Giữ nguyên raw.",
                          period_label)
        if pb is not None and pb == 0:
            self.diag.add(self.ticker, "SUSPICIOUS_PB",
                          "pb = 0. Kiểm tra raw KBS.", period_label)
        if roe is not None and abs(roe) > 200:
            self.diag.add(self.ticker, "SUSPICIOUS_ROE",
                          f"roe = {roe} nằm ngoài dải hợp lý. Giữ nguyên raw.",
                          period_label)
        if net_margin is not None and abs(net_margin) > 100:
            self.diag.add(self.ticker, "SUSPICIOUS_NET_MARGIN",
                          f"net_margin = {net_margin} > 100%. Giữ nguyên raw.",
                          period_label)
        if debt_equity is not None and debt_equity < 0:
            self.diag.add(self.ticker, "SUSPICIOUS_DEBT_EQUITY",
                          f"debt_equity = {debt_equity} âm. Giữ nguyên raw.",
                          period_label)

    def check_unit_consistency(
        self,
        history: List[Dict[str, Any]],
        kind: str,
    ) -> None:
        """
        Cảnh báo khi cùng một metric có kỳ |giá trị| < 1 và kỳ |giá trị| >= 1.

        CHỈ áp dụng cho kỳ NĂM.

        Lý do bỏ qua kỳ quý: bằng chứng từ PNJ cho thấy roe quý đã là
        percentage points (roe quý 9.65 + 4.14 + ... ~ roe_trailling 20.00).
        ROE/biên lợi nhuận MỘT QUÝ của doanh nghiệp yếu hoàn toàn có thể
        nhỏ hơn 1% một cách hợp lệ (VID 2025-Q4 roe 0.02). Chạy check này
        trên kỳ quý chỉ sinh cảnh báo giả.

        Kỳ năm thì khác: ROE/biên cả năm < 1% là hiếm, nên vẫn đáng soi.
        Dù vậy đây chỉ là CẢNH BÁO. Code không bao giờ tự scale.
        """
        if kind != "year":
            return

        for metric in ("roe", "net_margin"):
            values = [
                (row["period"], row[metric])
                for row in history
                if row.get(metric) is not None
            ]
            if len(values) < 2:
                continue

            small = [p for p, v in values if abs(v) < 1]
            large = [p for p, v in values if abs(v) >= 1]

            if small and large:
                self.diag.add(
                    self.ticker,
                    "UNIT_INCONSISTENCY",
                    f"{metric}: kỳ {small} có |giá trị| < 1 trong khi kỳ "
                    f"{large} có |giá trị| >= 1. Có thể KBS trả khác unit "
                    f"(0.94 = 0.94% hay 94%?). KHÔNG tự scale. "
                    f"Hãy kiểm tra raw bằng --debug-raw.",
                )

    def check_annual_eps_conflict(
        self,
        eps_ratio: Dict[Any, Optional[float]],
        eps_income: Dict[Any, Optional[float]],
    ) -> None:
        """
        So hai nguồn EPS năm. Nếu chúng chỉ khác nhau bởi MỘT hệ số scale
        không đổi thì chỉ là vấn đề đơn vị. Nếu hệ số nhảy loạn giữa các kỳ
        thì ít nhất một nguồn đang gán nhãn năm SAI KỲ.
        """
        factors: Dict[str, float] = {}
        for period in set(eps_ratio) & set(eps_income):
            a = eps_ratio.get(period)
            b = eps_income.get(period)
            if a in (None, 0) or b is None:
                continue
            factors[period.label()] = b / a

        if len(factors) < 2:
            return

        low, high = min(factors.values()), max(factors.values())
        if low <= 0 or high / low <= 1.1:
            return

        self.diag.add(
            self.ticker,
            "ANNUAL_EPS_CONFLICT",
            f"EPS năm từ ratio(year) và income_statement(year) không cùng một "
            f"hệ số scale: {', '.join(f'{k}={v:.1f}x' for k, v in sorted(factors.items()))}. "
            f"Ít nhất một nguồn gán nhãn năm sai kỳ. Đang dùng "
            f"ANNUAL_EPS_SOURCE='{ANNUAL_EPS_SOURCE}'.",
        )

    def check_implied_price(self, history: List[Dict[str, Any]]) -> None:
        """
        Với kỳ NĂM: EPS x PE = giá cổ phiếu tại thời điểm chốt năm.
        Giá có thể thay đổi giữa các năm, nhưng không thể nhảy vài lần
        theo kiểu ngẫu nhiên nếu EPS và PE cùng thuộc một kỳ.

        Đây là bài test đã phát hiện lỗi đảo kỳ của income_statement(year).
        """
        prices: Dict[str, float] = {}
        for row in history:
            eps, pe = row.get("eps"), row.get("pe")
            if eps is None or pe is None or eps <= 0 or pe <= 0:
                continue
            prices[row["period"]] = eps * pe

        if len(prices) < 2:
            return

        low, high = min(prices.values()), max(prices.values())
        if low <= 0:
            return

        spread = high / low
        if spread > IMPLIED_PRICE_SPREAD_THRESHOLD:
            self.diag.add(
                self.ticker,
                "PERIOD_ALIGNMENT_SUSPECT",
                f"Giá ngụ ý (EPS x PE) biến động {spread:.2f}x giữa các kỳ: "
                f"{', '.join(f'{k}={v:,.0f}' for k, v in sorted(prices.items()))}. "
                f"EPS và PE có thể KHÔNG cùng một kỳ. Kiểm tra raw.",
            )

    def check_margin_alignment(
        self,
        profit: Dict[Any, Optional[float]],
        revenue: Dict[Any, Optional[float]],
        ratio_margin: Dict[Any, Optional[float]],
        kind: str,
    ) -> str:
        """
        Đối chiếu đẳng thức kế toán:

            profit_after_tax / revenue * 100  ==  net_margin

        Vế trái từ income_statement(), vế phải từ ratio(). Nếu hai API gán
        nhãn kỳ giống nhau thì hai vế phải khớp cho CÙNG một nhãn.

        Đây là phép kiểm chứng đã xác minh:
            - income_statement(quarter) gán nhãn ĐÚNG
              (PNJ: 6.09 / 12.67 / 7.03 khớp tuyệt đối)
            - income_statement(year) gán nhãn ĐẢO NGƯỢC
              (GVT/MGC: 7/8 cặp khớp khi ghép ngược, tỉ lệ EPS đúng 1000.0)

        Hàm này chỉ BÁO CÁO. Nó không tự đảo lại dữ liệu, vì đảo tự động
        dựa trên suy luận thống kê chính là kiểu "đoán" mà spec cấm.
        """
        periods = sorted(
            [p for p in set(profit) & set(ratio_margin)
             if profit.get(p) is not None
             and revenue.get(p) not in (None, 0)
             and ratio_margin.get(p) is not None],
            key=lambda p: p.key(),
        )
        if len(periods) < 2:
            return "insufficient"

        computed = [profit[p] / revenue[p] * 100.0 for p in periods]
        reported = [ratio_margin[p] for p in periods]

        def close(a: float, b: float) -> bool:
            return abs(a - b) <= max(0.05, abs(b) * 0.02)

        direct = sum(close(c, r) for c, r in zip(computed, reported))
        if direct * 2 >= len(periods):
            self.diag.note(
                self.ticker,
                "PERIOD_ALIGNMENT_OK",
                f"[{kind}] profit/revenue khớp net_margin ở {direct}/"
                f"{len(periods)} kỳ -> nhãn kỳ của income_statement và ratio "
                f"nhất quán.",
            )
            return "ok"

        reversed_hits = sum(
            close(c, r) for c, r in zip(computed, list(reversed(reported)))
        )
        detail = ", ".join(
            f"{p.label()}: tính {c:.2f} vs ratio {r:.2f}"
            for p, c, r in zip(periods, computed, reported)
        )

        if reversed_hits * 2 >= len(periods):
            self.diag.add(
                self.ticker,
                "INCOME_PERIODS_REVERSED",
                f"[{kind}] profit/revenue KHÔNG khớp net_margin theo nhãn "
                f"({direct}/{len(periods)}) nhưng khớp khi ghép ĐẢO NGƯỢC "
                f"({reversed_hits}/{len(periods)}). Nhãn kỳ của "
                f"income_statement({kind}) nhiều khả năng bị đảo. "
                f"Không dùng EPS/revenue từ nguồn này cho kỳ đó. {detail}",
            )
            return "reversed"
        else:
            self.diag.add(
                self.ticker,
                "MARGIN_MISMATCH",
                f"[{kind}] profit/revenue không khớp net_margin của ratio "
                f"({direct}/{len(periods)} kỳ) và cũng không khớp khi đảo "
                f"ngược. Có thể khác định nghĩa doanh thu hoặc khác kỳ. "
                f"{detail}",
            )
            return "mismatch"

    def check_margin_alignment_with_fallback(
        self,
        profit_parent: Dict[Any, Optional[float]],
        profit_total: Dict[Any, Optional[float]],
        revenue: Dict[Any, Optional[float]],
        ratio_margin: Dict[Any, Optional[float]],
        kind: str,
    ) -> str:
        """
        Thử check_margin_alignment với lợi nhuận CỔ ĐÔNG CÔNG TY MẸ trước
        (đúng định nghĩa của field "net_profit" xuất ra JSON). Nếu KHÔNG
        khớp, thử lại với lợi nhuận TOÀN CÔNG TY trước khi kết luận lệch kỳ.

        Lý do (phát hiện từ VID): ratio() có thể tính net_margin bằng lợi
        nhuận TOÀN công ty (bao gồm lợi ích cổ đông thiểu số), trong khi
        field "net_profit" của nhóm luôn là lợi nhuận cổ đông công ty mẹ.
        Với mã có cổ đông thiểu số, hai định nghĩa lệch nhau dù nhãn kỳ
        HOÀN TOÀN đúng - không được coi đó là lệch kỳ rồi null oan dữ liệu.

        Trả về:
            "parent"      - khớp bằng định nghĩa cổ đông công ty mẹ, giữ
                             nguyên revenue/profit_parent.
            "total"       - chỉ khớp khi dùng lợi nhuận toàn công ty; VẪN
                             giữ nguyên revenue/profit_parent cho output
                             (đúng convention), chỉ khác cách hiểu vì sao
                             ratio() lệch - KHÔNG null.
            "reversed" / "mismatch" / "insufficient" - như
            check_margin_alignment gốc; caller tự quyết null hay không.
        """
        status = self.check_margin_alignment(
            profit_parent, revenue, ratio_margin, kind
        )
        if status == "ok":
            return "parent"

        if status in ("reversed", "mismatch") and profit_total:
            status2 = self.check_margin_alignment(
                profit_total, revenue, ratio_margin, f"{kind}-tổng NPAT (thử lại)"
            )
            if status2 == "ok":
                self.diag.note(
                    self.ticker,
                    "NET_MARGIN_USES_TOTAL_PROFIT",
                    f"[{kind}] net_margin của ratio() khớp khi dùng LỢI "
                    f"NHUẬN TOÀN CÔNG TY (item_id='net_profit'), không phải "
                    f"lợi nhuận cổ đông công ty mẹ - mã này có lợi ích cổ "
                    f"đông thiểu số đáng kể. Field 'net_profit' xuất ra vẫn "
                    f"dùng định nghĩa cổ đông công ty mẹ (đúng convention). "
                    f"KHÔNG null vì đây chỉ là khác định nghĩa lợi nhuận, "
                    f"không phải lệch kỳ.",
                )
                return "total"

        return status

    def check_growth(
        self,
        period_label: str,
        metric: str,
        current: Optional[float],
        previous: Optional[float],
        growth: Optional[float],
    ) -> None:
        if growth is None or current is None or previous is None:
            return
        if previous < 0 < current or current < 0 < previous:
            self.diag.note(
                self.ticker,
                "GROWTH_SIGN_CHANGE",
                f"{metric} đổi dấu ({previous} -> {current}), growth "
                f"{round(growth, 2)}% tính đúng công thức nhưng khó diễn giải "
                f"về mặt kinh tế.",
                period_label,
            )
        elif abs(growth) > 1000:
            self.diag.note(
                self.ticker,
                "GROWTH_EXTREME",
                f"{metric} growth = {round(growth, 2)}% "
                f"({previous} -> {current}). Giá trị cực đoan nhưng hợp lệ "
                f"theo công thức.",
                period_label,
            )


def build_reversal_mapping(periods: List[Period]) -> Dict[Period, Period]:
    """
    Với danh sách kỳ đã phát hiện bị ĐẢO NHÃN (INCOME_PERIODS_REVERSED),
    trả về ánh xạ: nhãn-sai (income) -> nhãn-đúng (theo thứ tự đảo ngược).

    Chỉ dùng khi ALLOW_INCOME_YEAR_REVERSAL_CORRECTION = True.
    """
    ordered = sorted(periods, key=lambda p: p.key())
    reversed_ordered = list(reversed(ordered))
    return dict(zip(ordered, reversed_ordered))


# ==============================================================
# VNF ANNUAL LOADER (revenue / net_profit / cfo NĂM - HSX/HNX)
# ==============================================================

class VnfAnnualLoader:
    """
    Tải BULK (một lần cho toàn bộ HSX + HNX, không phải theo từng ticker)
    revenue / net_profit / cfo năm từ package vnfinancialdata.

    Quan trọng: KHÔNG phủ UPCOM (đã xác nhận bằng test thực tế của nhóm -
    API trả "Unsupported exchange: UPCOM"). Với UPCOM, .get(ticker) trả
    {} một cách tự nhiên (không tìm thấy trong index), không cần đoán
    hay xử lý riêng.

    KHÔNG có tham số quý - class này CHỈ phục vụ dữ liệu NĂM.
    """

    def __init__(self, diagnostics: Diagnostics):
        self.diag = diagnostics
        self._data: Dict[str, Dict[str, Dict[str, Optional[float]]]] = {}
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True

        if _vnf is None:
            logger.warning(
                "  [WARNING] Chưa cài vnfinancialdata (pip install "
                "vnfinancialdata) -> revenue/net_profit/cfo năm cho "
                "HSX/HNX sẽ null. UPCOM không bị ảnh hưởng (vốn dĩ không "
                "được vnf hỗ trợ)."
            )
            return

        logger.info(
            "\nĐang tải bulk revenue/net_profit/cfo từ vnfinancialdata "
            f"({', '.join(VNF_EXCHANGES)})..."
        )
        for exchange in VNF_EXCHANGES:
            self._load_statement(
                exchange, "income_statement",
                {VNF_ITEM_REVENUE: "revenue", VNF_ITEM_NET_PROFIT: "net_profit"},
            )
            self._load_statement(
                exchange, "cash_flow",
                {VNF_ITEM_CFO: "cfo"},
            )

    def _load_statement(
        self,
        exchange: str,
        statement: str,
        item_map: Dict[str, str],
    ) -> None:
        tag = f"vnfinancialdata {statement}/{exchange}"
        try:
            df = _vnf.load(exchange=exchange, statement=statement)
        except Exception as exc:
            self.diag.add("__VNF_BULK__", "VNF_LOAD_FAILED",
                          f"{tag}: tải thất bại ({exc}). Bỏ qua.")
            return

        if df is None or df.empty:
            self.diag.add("__VNF_BULK__", "VNF_EMPTY",
                          f"{tag}: DataFrame rỗng. Bỏ qua.")
            return

        required = {"ticker", "year", "item_code"}
        missing = required - set(df.columns)
        if missing:
            self.diag.add(
                "__VNF_BULK__", "VNF_MISSING_COLUMNS",
                f"{tag}: thiếu cột {sorted(missing)}. "
                f"Cột thực tế: {list(df.columns)}. Bỏ qua nguồn này - "
                f"KHÔNG đoán tên cột.",
            )
            return

        value_col = next(
            (c for c in VNF_VALUE_COLUMN_CANDIDATES if c in df.columns),
            None,
        )
        if value_col is None:
            self.diag.add(
                "__VNF_BULK__", "VNF_VALUE_COLUMN_UNKNOWN",
                f"{tag}: không xác định được cột giá trị trong "
                f"{list(df.columns)} (đã thử {VNF_VALUE_COLUMN_CANDIDATES}). "
                f"Cần xác nhận thủ công tên cột rồi thêm vào "
                f"VNF_VALUE_COLUMN_CANDIDATES. Bỏ qua nguồn này.",
            )
            return

        subset = df[df["item_code"].isin(item_map.keys())]
        count = 0
        for _, row in subset.iterrows():
            ticker = str(row["ticker"]).strip().upper()
            if not ticker:
                continue
            try:
                year = int(row["year"])
            except (TypeError, ValueError):
                continue

            period_label = f"{year}-Năm"
            field = item_map[row["item_code"]]
            value = safe_float(row[value_col])

            bucket = self._data.setdefault(ticker, {}).setdefault(
                period_label, {"revenue": None, "net_profit": None, "cfo": None}
            )
            if value is not None:
                bucket[field] = value
                count += 1

        logger.info(
            f"  {tag} -> {count} giá trị hợp lệ "
            f"({', '.join(item_map.values())}), cột giá trị = '{value_col}'."
        )

    def get(self, ticker: str) -> Dict[str, Dict[str, Optional[float]]]:
        """period_label ('20XX-Năm') -> {revenue, net_profit, cfo}."""
        return self._data.get(ticker.strip().upper(), {})


# ==============================================================
# EMPTY ROW
# ==============================================================

def empty_history_row(period_label: str) -> Dict[str, Any]:
    """Khung một dòng history. Đúng schema, mọi metric mặc định null."""
    return {
        "period": period_label,
        "eps": None,
        "pe": None,
        "pb": None,
        "roe": None,
        "debt_equity": None,
        "net_margin": None,
        "eps_growth_qoq": None,
        "eps_growth_yoy": None,
        "revenue_growth_qoq": None,
        "revenue": None,
        "net_profit": None,
        "cfo": None,
        "cfo_ttm": None,
    }


HISTORY_FIELDS = tuple(empty_history_row("x").keys())


# ==============================================================
# FETCHER
# ==============================================================

class FinancialDataFetcher:
    """
    Fetcher chính. Một instance dùng cho cả phiên chạy.
    """

    def __init__(
        self,
        request_delay: float = 1.5,
        max_retries: int = 3,
        rate_limit_sleep: float = 35.0,
        debug_raw: bool = False,
        vnf_loader: Optional[VnfAnnualLoader] = None,
    ):
        self.source = SOURCE
        self.request_delay = request_delay
        self.max_retries = max_retries
        self.rate_limit_sleep = rate_limit_sleep
        self.debug_raw = debug_raw
        self.diag = Diagnostics()
        # Nguồn revenue/net_profit/cfo NĂM cho HSX/HNX (bulk, tải 1 lần).
        self.vnf_loader = vnf_loader

    # ----------------------------------------------------------
    # LỚP GỌI API
    # ----------------------------------------------------------

    def _call(self, finance: Any, method: str, ticker: str, **kwargs):
        """
        Gọi một endpoint của vnstock. Trả (DataFrame | None).
        Mọi exception được nuốt tại đây và ghi diagnostics,
        trừ rate limit (được ném lên để retry).
        """
        # Nghỉ chủ động 3.5 giây trước mỗi lượt gọi
        time.sleep(3.5)
        try:
            df = getattr(finance, method)(**kwargs)
        except Exception as exc:
            message = str(exc).lower()
            if any(k in message for k in
                   ("rate limit", "exceeded", "too many", "giới hạn", "429")):
                raise
            self.diag.add(
                ticker,
                "API_ERROR",
                f"{method}({kwargs}) lỗi: {exc}",
            )
            return None

        df = flatten_columns(df)

        if df is None or df.empty:
            self.diag.note(ticker, "EMPTY_DATAFRAME",
                           f"{method}({kwargs}) trả DataFrame rỗng.")
            return None

        if self.debug_raw:
            self._dump_raw(ticker, method, kwargs, df)

        return df

    def _dump_raw(self, ticker: str, method: str,
                  kwargs: Dict[str, Any], df: pd.DataFrame) -> None:
        """In raw response để bạn đối chiếu unit/row/column thật của KBS."""
        tag = f"{ticker} :: {method}({kwargs})"
        logger.info(f"\n----- RAW {tag} -----")
        logger.info(f"columns: {list(df.columns)}")
        if "item_id" in df.columns:
            logger.info(f"item_id: {df['item_id'].astype(str).tolist()}")
        with pd.option_context("display.max_columns", None,
                               "display.width", 200):
            logger.info(df.to_string())
        logger.info(f"----- END RAW {tag} -----\n")

    # ----------------------------------------------------------
    # TRÍCH XUẤT RATIO CHO MỘT KỲ
    # ----------------------------------------------------------

    def _ratio_rows(
        self,
        df_ratio: pd.DataFrame,
        rows: RowResolver,
        df_name: str,
    ) -> Dict[str, Optional[Any]]:
        """Tìm index của từng metric MỘT LẦN cho cả DataFrame."""
        found: Dict[str, Optional[Any]] = {}
        for metric, item_ids in RATIO_ROW_IDS.items():
            found[metric] = rows.find_one(df_ratio, item_ids, metric, df_name)
        return found

    def _extract_ratio(
        self,
        df_ratio: Optional[pd.DataFrame],
        row_map: Dict[str, Optional[Any]],
        column: Optional[str],
    ) -> Dict[str, Optional[float]]:
        """
        Lấy 5 metric cho ĐÚNG một cột.
        column = None (ratio không có kỳ này) -> tất cả None. Không thay thế.
        """
        result: Dict[str, Optional[float]] = {}
        for metric in RATIO_ROW_IDS:
            result[metric] = get_cell(df_ratio, row_map.get(metric), column)
        return result

    # ----------------------------------------------------------
    # QUARTERLY
    # ----------------------------------------------------------

    def _build_quarter_history(
        self,
        ticker: str,
        df_income: pd.DataFrame,
        df_ratio: Optional[pd.DataFrame],
    ) -> List[Dict[str, Any]]:

        resolver = PeriodResolver(self.diag, ticker)
        rows = RowResolver(self.diag, ticker)
        detector = SuspicionDetector(self.diag, ticker)

        income_cols = resolver.resolve(df_income, "quarter", "income_statement")
        ratio_cols = (
            resolver.resolve(df_ratio, "quarter", "ratio")
            if df_ratio is not None else {}
        )

        if not income_cols:
            return []

        # -- các dòng cần dùng, tìm một lần ---------------------
        eps_row = rows.find_one(df_income, INCOME_EPS_IDS, "eps",
                                "income_statement")
        revenue_row = rows.find_revenue_row(df_income, "income_statement")
        ratio_row_map = (
            self._ratio_rows(df_ratio, rows, "ratio")
            if df_ratio is not None else {}
        )

        if eps_row is None:
            self.diag.add(
                ticker,
                "EPS_ROW_NOT_FOUND",
                f"income_statement không có dòng nào trong {INCOME_EPS_IDS}. "
                f"EPS quý sẽ là null. KHÔNG thay thế bằng trailing_eps.",
            )

        # -- map TOÀN BỘ kỳ (trước khi cắt) ---------------------
        # YoY phải được tìm trong toàn bộ dữ liệu API trả, không chỉ 4 kỳ output.
        eps_map: Dict[Period, Optional[float]] = {}
        revenue_map: Dict[Period, Optional[float]] = {}
        profit_map: Dict[Period, Optional[float]] = {}
        total_profit_map: Dict[Period, Optional[float]] = {}
        profit_row = rows.find_one(df_income, INCOME_PROFIT_IDS, "profit",
                                   "income_statement")
        # Chỉ dùng để đối chiếu (xem check_margin_alignment_with_fallback),
        # KHÔNG BAO GIỜ dùng làm giá trị field "net_profit" xuất ra.
        total_profit_row = rows.find_one(df_income, INCOME_TOTAL_PROFIT_IDS,
                                         "net_profit_total", "income_statement")
        for period, column in income_cols.items():
            eps_map[period] = get_cell(df_income, eps_row, column)
            revenue_map[period] = get_cell(df_income, revenue_row, column)
            profit_map[period] = get_cell(df_income, profit_row, column)
            total_profit_map[period] = get_cell(df_income, total_profit_row,
                                                column)

        # -- đối chiếu profit/revenue vs net_margin của ratio() TRƯỚC khi
        # dùng revenue/net_profit cho output, để không lỡ xuất dữ liệu
        # lệch kỳ (xem check_margin_alignment / INCOME_PERIODS_REVERSED).
        # Thử cả 2 định nghĩa lợi nhuận (cổ đông công ty mẹ / toàn công ty)
        # trước khi kết luận lệch kỳ - xem check_margin_alignment_with_fallback. --
        ratio_margin_map_early = {
            period: get_cell(df_ratio, ratio_row_map.get("net_margin"), column)
            for period, column in ratio_cols.items()
        }
        alignment_status = detector.check_margin_alignment_with_fallback(
            profit_map, total_profit_map, revenue_map, ratio_margin_map_early,
            "quarter",
        )
        if alignment_status in ("reversed", "mismatch"):
            self.diag.add(
                ticker,
                "REVENUE_NET_PROFIT_NULLED",
                f"[quarter] revenue/net_profit bị đặt null vì "
                f"check_margin_alignment trả '{alignment_status}' (đã thử "
                f"cả 2 định nghĩa lợi nhuận) - xem cảnh báo tương ứng ở "
                f"trên. Đây là biện pháp an toàn theo nguyên tắc DATA "
                f"ACCURACY, không phải do thiếu dữ liệu.",
            )
            revenue_map = {p: None for p in revenue_map}
            profit_map = {p: None for p in profit_map}

        all_periods = sorted(income_cols.keys(), key=lambda p: p.key())
        selected = all_periods[-MAX_PERIODS:]

        logger.info(
            f"  {ticker}: Đã lấy {len(selected)} quý gần đây"
        )
        logger.info(
            f"    Kỳ: {', '.join(p.label() for p in selected)}"
        )

        if len(all_periods) <= MAX_PERIODS:
            self.diag.note(
                ticker,
                "PERIOD_LIMIT",
                f"income_statement chỉ trả {len(all_periods)} kỳ "
                f"({', '.join(p.label() for p in all_periods)}). "
                f"Community Edition giới hạn 4 kỳ -> eps_growth_yoy theo quý "
                f"thường không tính được.",
            )

        history: List[Dict[str, Any]] = []

        for period in selected:
            label = period.label()
            row = empty_history_row(label)

            # ---- EPS / metric ----
            eps = eps_map.get(period)
            row["eps"] = round_or_none(eps)
            row["revenue"] = round_or_none(revenue_map.get(period))
            row["net_profit"] = round_or_none(profit_map.get(period))

            ratio_column = ratio_cols.get(period)
            if ratio_column is None:
                self.diag.note(
                    ticker,
                    "RATIO_PERIOD_MISSING",
                    "ratio() không có kỳ này -> pe/pb/roe/debt_equity/"
                    "net_margin = null. KHÔNG lấy từ kỳ khác.",
                    label,
                )
                logger.info(
                    f"    {label}: pe/pb/roe/debt_equity/net_margin "
                    f"unavailable (ratio không có kỳ này)"
                )
            else:
                ratio_values = self._extract_ratio(
                    df_ratio, ratio_row_map, ratio_column
                )
                for metric, value in ratio_values.items():
                    row[metric] = round_or_none(value)

                missing = [m for m, v in ratio_values.items() if v is None]
                if missing:
                    logger.info(
                        f"    {label}: {', '.join(missing)} unavailable"
                    )

            # ---- growth QoQ: chỉ với quý LIỀN KỀ thật ----
            previous_quarter = period.previous_quarter()
            if previous_quarter in eps_map:
                previous_eps = eps_map[previous_quarter]
                growth = calc_growth(eps, previous_eps)
                row["eps_growth_qoq"] = round_or_none(growth)
                detector.check_growth(label, "eps", eps, previous_eps, growth)
            else:
                self.diag.note(
                    ticker, "QOQ_NO_PREVIOUS",
                    f"không có {previous_quarter.label() if previous_quarter else '?'}"
                    f" -> eps_growth_qoq = null.",
                    label,
                )

            if previous_quarter in revenue_map:
                previous_revenue = revenue_map[previous_quarter]
                current_revenue = revenue_map.get(period)
                growth = calc_growth(current_revenue, previous_revenue)
                row["revenue_growth_qoq"] = round_or_none(growth)
                detector.check_growth(label, "revenue", current_revenue,
                                      previous_revenue, growth)

            # ---- growth YoY: cùng quý năm trước, phải có THẬT ----
            same_quarter_last_year = period.previous_year_same_quarter()
            if same_quarter_last_year in eps_map:
                previous_eps = eps_map[same_quarter_last_year]
                growth = calc_growth(eps, previous_eps)
                row["eps_growth_yoy"] = round_or_none(growth)
                detector.check_growth(label, "eps_yoy", eps, previous_eps,
                                      growth)
            else:
                self.diag.note(
                    ticker, "YOY_NO_SAME_QUARTER",
                    f"API không trả "
                    f"{same_quarter_last_year.label() if same_quarter_last_year else '?'}"
                    f" -> eps_growth_yoy = null (null hợp lệ).",
                    label,
                )

            detector.check_row(label, row)
            history.append(row)

        detector.check_unit_consistency(history, "quarter")
        self.diag.note(
            ticker,
            "CFO_NOT_AVAILABLE_QUARTER",
            "Không có nguồn CFO theo quý (KBS quarter không có cash_flow, "
            "vnfinancialdata chỉ có năm) -> cfo/cfo_ttm luôn null ở kỳ quý.",
        )
        return history

    # ----------------------------------------------------------
    # ANNUAL FALLBACK
    # ----------------------------------------------------------

    def _build_year_history(
        self,
        ticker: str,
        df_ratio_year: Optional[pd.DataFrame],
        df_income_year: Optional[pd.DataFrame],
        vnf_annual: Optional[Dict[str, Dict[str, Optional[float]]]] = None,
    ) -> List[Dict[str, Any]]:

        vnf_annual = vnf_annual or {}

        if df_ratio_year is None and df_income_year is None and not vnf_annual:
            return []

        resolver = PeriodResolver(self.diag, ticker)
        rows = RowResolver(self.diag, ticker)
        detector = SuspicionDetector(self.diag, ticker)

        ratio_cols = (
            resolver.resolve(df_ratio_year, "year", "ratio(year)")
            if df_ratio_year is not None else {}
        )
        income_cols = (
            resolver.resolve(df_income_year, "year", "income_statement(year)")
            if df_income_year is not None else {}
        )

        # ---- EPS năm: lấy CẢ HAI nguồn để đối chiếu ----
        eps_from_ratio: Dict[Period, Optional[float]] = {}
        eps_from_income: Dict[Period, Optional[float]] = {}

        if ratio_cols:
            eps_row = rows.find_one(df_ratio_year, RATIO_YEAR_EPS_IDS,
                                    "eps", "ratio(year)")
            if eps_row is not None:
                for period, column in ratio_cols.items():
                    eps_from_ratio[period] = get_cell(
                        df_ratio_year, eps_row, column
                    )

        if income_cols:
            eps_row = rows.find_one(df_income_year, INCOME_EPS_IDS,
                                    "eps", "income_statement(year)")
            if eps_row is not None:
                for period, column in income_cols.items():
                    eps_from_income[period] = get_cell(
                        df_income_year, eps_row, column
                    )

        detector.check_annual_eps_conflict(eps_from_ratio, eps_from_income)

        candidates = {
            "ratio": ("ratio(year)", eps_from_ratio),
            "income": ("income_statement(year)", eps_from_income),
        }
        eps_source, eps_map = candidates[ANNUAL_EPS_SOURCE]

        if not any(v is not None for v in eps_map.values()):
            other = "income" if ANNUAL_EPS_SOURCE == "ratio" else "ratio"
            fallback_source, fallback_map = candidates[other]
            if any(v is not None for v in fallback_map.values()):
                self.diag.add(
                    ticker,
                    "ANNUAL_EPS_FALLBACK",
                    f"Nguồn EPS năm ưu tiên ('{ANNUAL_EPS_SOURCE}') không có "
                    f"dữ liệu. Dùng {fallback_source} thay thế. Kỳ của EPS có "
                    f"thể không khớp kỳ của PE/PB/ROE - xem "
                    f"PERIOD_ALIGNMENT_SUSPECT.",
                )
                eps_source, eps_map = fallback_source, fallback_map
            else:
                eps_map = {}

        if eps_source == "ratio(year)" and eps_map:
            self.diag.note(
                ticker,
                "ANNUAL_EPS_FROM_RATIO",
                "EPS năm lấy từ ratio(year). Hàng này có thể là trailing_eps; "
                "tại thời điểm chốt năm trailing 4 quý = EPS cả năm, và nó "
                "khớp kỳ với PE/PB/ROE (xem check_implied_price).",
            )

        all_periods = sorted(
            set(ratio_cols.keys()) | set(eps_map.keys()),
            key=lambda p: p.key(),
        )
        if not all_periods:
            return []

        selected = all_periods[-MAX_PERIODS:]

        ratio_row_map = (
            self._ratio_rows(df_ratio_year, rows, "ratio(year)")
            if df_ratio_year is not None else {}
        )

        # -- revenue / net_profit năm từ KBS income_statement(year) --------
        # (chỉ dùng khi vnf KHÔNG phủ ticker này - xem gộp bên dưới).
        # Đã biết income_statement(year) của KBS có thể ĐẢO NHÃN KỲ (mục
        # PHIÊN BẢN 2 / ANNUAL_EPS_CONFLICT). Phải đối chiếu trước khi dùng.
        kbs_revenue_map: Dict[Period, Optional[float]] = {}
        kbs_profit_map: Dict[Period, Optional[float]] = {}
        kbs_total_profit_map: Dict[Period, Optional[float]] = {}

        if income_cols:
            kbs_revenue_row = rows.find_revenue_row(
                df_income_year, "income_statement(year)"
            )
            kbs_profit_row = rows.find_one(
                df_income_year, INCOME_PROFIT_IDS, "profit",
                "income_statement(year)",
            )
            # Chỉ để đối chiếu (xem check_margin_alignment_with_fallback).
            kbs_total_profit_row = rows.find_one(
                df_income_year, INCOME_TOTAL_PROFIT_IDS, "net_profit_total",
                "income_statement(year)",
            )
            for period, column in income_cols.items():
                kbs_revenue_map[period] = get_cell(
                    df_income_year, kbs_revenue_row, column
                )
                kbs_profit_map[period] = get_cell(
                    df_income_year, kbs_profit_row, column
                )
                kbs_total_profit_map[period] = get_cell(
                    df_income_year, kbs_total_profit_row, column
                )

            ratio_margin_map_year = {
                period: get_cell(df_ratio_year,
                                 ratio_row_map.get("net_margin"), column)
                for period, column in ratio_cols.items()
            }
            income_year_status = detector.check_margin_alignment_with_fallback(
                kbs_profit_map, kbs_total_profit_map, kbs_revenue_map,
                ratio_margin_map_year, "year(income_statement KBS)",
            )

            if income_year_status == "reversed":
                if ALLOW_INCOME_YEAR_REVERSAL_CORRECTION:
                    mapping = build_reversal_mapping(list(kbs_revenue_map.keys()))
                    kbs_revenue_map = {
                        mapping[p]: v for p, v in kbs_revenue_map.items()
                        if p in mapping
                    }
                    kbs_profit_map = {
                        mapping[p]: v for p, v in kbs_profit_map.items()
                        if p in mapping
                    }
                    self.diag.add(
                        ticker,
                        "INCOME_YEAR_REVERSAL_CORRECTED",
                        "Đã TỰ ĐẢO nhãn kỳ cho revenue/net_profit từ "
                        "income_statement(year) vì "
                        "ALLOW_INCOME_YEAR_REVERSAL_CORRECTION=True và phát "
                        "hiện đảo nhãn nhất quán. Đây là suy luận dựa trên "
                        "đối chiếu số liệu, KHÔNG phải xác nhận từ tài liệu "
                        "API - hãy tự chịu trách nhiệm khi bật cờ này.",
                    )
                else:
                    kbs_revenue_map = {p: None for p in kbs_revenue_map}
                    kbs_profit_map = {p: None for p in kbs_profit_map}
                    self.diag.add(
                        ticker,
                        "INCOME_YEAR_REVENUE_NULLED",
                        "revenue/net_profit năm từ income_statement(year) bị "
                        "đặt null vì phát hiện đảo nhãn kỳ (xem "
                        "INCOME_PERIODS_REVERSED). Đặt "
                        "ALLOW_INCOME_YEAR_REVERSAL_CORRECTION=True nếu muốn "
                        "tự sửa (cần tự kiểm chứng thêm trước khi bật).",
                    )
            elif income_year_status == "mismatch":
                kbs_revenue_map = {p: None for p in kbs_revenue_map}
                kbs_profit_map = {p: None for p in kbs_profit_map}
                self.diag.add(
                    ticker,
                    "INCOME_YEAR_REVENUE_NULLED",
                    "revenue/net_profit năm từ income_statement(year) bị đặt "
                    "null vì không khớp net_margin của ratio (xem "
                    "MARGIN_MISMATCH) và cũng không khớp khi đảo ngược.",
                )
            # "parent" (khớp bằng lợi nhuận cổ đông công ty mẹ), "total"
            # (chỉ khớp bằng lợi nhuận toàn công ty - có cổ đông thiểu số,
            # xem NET_MARGIN_USES_TOTAL_PROFIT) hoặc "insufficient" (chưa
            # đủ dữ liệu để bác bỏ): đều giữ nguyên giá trị đã trích xuất.

        if vnf_annual:
            self.diag.note(
                ticker, "VNF_ANNUAL_AVAILABLE",
                f"vnfinancialdata có dữ liệu năm cho mã này "
                f"({', '.join(sorted(vnf_annual.keys()))}) -> ưu tiên dùng "
                f"cho revenue/net_profit/cfo.",
            )
        else:
            self.diag.note(
                ticker, "VNF_ANNUAL_UNAVAILABLE",
                "vnfinancialdata không có dữ liệu cho mã này (không thuộc "
                "HSX/HNX, hoặc chưa cài đặt) -> cfo năm = null; "
                "revenue/net_profit năm (nếu có) lấy từ KBS income_statement.",
            )

        logger.info(f"  {ticker}: Đã lấy {len(selected)} năm"
                    f" (EPS từ {eps_source or 'không có nguồn'})")
        logger.info(f"    Kỳ: {', '.join(p.label() for p in selected)}")

        history: List[Dict[str, Any]] = []

        for period in selected:
            label = period.label()
            row = empty_history_row(label)

            eps = eps_map.get(period)
            row["eps"] = round_or_none(eps)

            # revenue / net_profit: ưu tiên vnfinancialdata (HSX/HNX, đã
            # xác nhận nhãn kỳ đúng vì dùng năm dương lịch trực tiếp);
            # nếu không có, dùng KBS income_statement(year) (đã được gate
            # ở trên - null nếu phát hiện đảo nhãn/không khớp margin).
            vnf_entry = vnf_annual.get(label)
            revenue = vnf_entry.get("revenue") if vnf_entry else None
            if revenue is None:
                revenue = kbs_revenue_map.get(period)
            net_profit = vnf_entry.get("net_profit") if vnf_entry else None
            if net_profit is None:
                net_profit = kbs_profit_map.get(period)
            # cfo: CHỈ có từ vnfinancialdata. KBS không có cash_flow(year)
            # trong pipeline này -> không có nguồn thay thế, không đoán.
            cfo = vnf_entry.get("cfo") if vnf_entry else None

            row["revenue"] = round_or_none(revenue)
            row["net_profit"] = round_or_none(net_profit)
            row["cfo"] = round_or_none(cfo)
            # cfo_ttm: chưa triển khai (xem ghi chú CFO_TTM_NOT_IMPLEMENTED).

            ratio_column = ratio_cols.get(period)
            if ratio_column is None:
                self.diag.note(ticker, "RATIO_PERIOD_MISSING",
                               "ratio(year) không có kỳ này -> metric null.",
                               label)
            else:
                values = self._extract_ratio(df_ratio_year, ratio_row_map,
                                             ratio_column)
                for metric, value in values.items():
                    row[metric] = round_or_none(value)
                missing = [m for m, v in values.items() if v is None]
                if missing:
                    logger.info(f"    {label}: {', '.join(missing)} unavailable")

            # YoY năm: năm liền trước, phải có thật
            previous_year = period.previous_year_same_quarter()
            if previous_year in eps_map:
                previous_eps = eps_map[previous_year]
                growth = calc_growth(eps, previous_eps)
                row["eps_growth_yoy"] = round_or_none(growth)
                detector.check_growth(label, "eps_yoy", eps, previous_eps,
                                      growth)

            # Kỳ năm không có QoQ và không có revenue QoQ -> giữ null.
            detector.check_row(label, row)
            history.append(row)

        self.diag.note(
            ticker, "CFO_TTM_NOT_IMPLEMENTED",
            "cfo_ttm cần cộng dồn 4 quý CFO liên tiếp; hiện không có nguồn "
            "CFO theo quý đáng tin cậy -> cfo_ttm luôn null (chưa triển "
            "khai, không suy đoán).",
        )
        detector.check_unit_consistency(history, "year")
        detector.check_implied_price(history)
        return history

    # ----------------------------------------------------------
    # VNF-ONLY ANNUAL ADDON (khi ticker ĐÃ có quý hợp lệ)
    # ----------------------------------------------------------

    def _build_vnf_only_annual_rows(
        self,
        ticker: str,
        vnf_annual: Dict[str, Dict[str, Optional[float]]],
    ) -> List[Dict[str, Any]]:
        """
        Thêm các dòng "20XX-Năm" CHỈ chứa revenue/net_profit/cfo, dùng khi
        ticker đã có dữ liệu quý hợp lệ (nên KHÔNG gọi thêm KBS annual để
        khỏi tốn thêm lệnh gọi API / rủi ro rate limit). eps/pe/pb/roe/
        debt_equity/net_margin của các dòng này để null có chủ đích.

        vnf được tải BULK một lần cho toàn bộ HSX/HNX (xem VnfAnnualLoader),
        nên hàm này không tốn thêm bất kỳ lệnh gọi mạng nào.
        """
        if not vnf_annual:
            return []

        labels = sorted(
            vnf_annual.keys(),
            key=lambda lbl: Period.parse(lbl[: -len("-Năm")], "year").key(),
        )
        selected = labels[-MAX_PERIODS:]

        rows: List[Dict[str, Any]] = []
        for label in selected:
            entry = vnf_annual[label]
            row = empty_history_row(label)
            row["revenue"] = round_or_none(entry.get("revenue"))
            row["net_profit"] = round_or_none(entry.get("net_profit"))
            row["cfo"] = round_or_none(entry.get("cfo"))
            rows.append(row)

        self.diag.note(
            ticker,
            "VNF_ANNUAL_ADDON",
            f"Thêm {len(rows)} dòng năm ({', '.join(selected)}) từ "
            f"vnfinancialdata cho revenue/net_profit/cfo, bên cạnh dữ liệu "
            f"quý đã có. eps/pe/pb/roe/debt_equity/net_margin của các dòng "
            f"này để null (không gọi thêm KBS annual để tiết kiệm API).",
        )
        return rows

    # ----------------------------------------------------------
    # PUBLIC: MỘT TICKER
    # ----------------------------------------------------------

    def fa_fetch_ticker(
        self,
        ticker: str,
        sector: str = DEFAULT_SECTOR,
    ) -> Optional[Dict[str, Any]]:
        """
        Trả về dict đúng schema, hoặc None nếu không có dữ liệu dùng được.
        Không bao giờ raise.

        Kiến trúc (xem "QUYẾT ĐỊNH KIẾN TRÚC QUAN TRỌNG" ở đầu file):
            - Có quý hợp lệ -> quý + (nếu vnf phủ) thêm dòng năm chỉ chứa
              revenue/net_profit/cfo, không tốn thêm lệnh gọi KBS.
            - Không có quý -> fallback năm đầy đủ (KBS ratio/income NĂM,
              gộp với vnf nếu có) như trước.
        """
        ticker = str(ticker).strip().upper()
        if not ticker:
            return None

        if Finance is None:
            raise RuntimeError(
                "Chưa cài vnstock. Chạy: pip install -U vnstock"
            )

        vnf_annual = self.vnf_loader.get(ticker) if self.vnf_loader else {}

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(f"\nĐang lấy dữ liệu {ticker}...")
                finance = Finance(symbol=ticker, source=self.source)

                # ---------- QUARTER ----------
                df_income_q = self._call(finance, "income_statement",
                                         ticker, period="quarter")
                time.sleep(0.3)
                df_ratio_q = self._call(finance, "ratio",
                                        ticker, period="quarter")

                history: List[Dict[str, Any]] = []

                if df_income_q is not None:
                    history = self._build_quarter_history(
                        ticker, df_income_q, df_ratio_q
                    )

                    # Nếu toàn bộ EPS null thì quarterly coi như không dùng được.
                    if history and all(r["eps"] is None for r in history):
                        self.diag.add(
                            ticker,
                            "QUARTER_EPS_ALL_NULL",
                            "Có cột quý nhưng toàn bộ EPS = null "
                            "-> chuyển sang dữ liệu năm.",
                        )
                        history = []

                if history:
                    # Đã có quý hợp lệ -> chỉ BỔ SUNG dòng năm từ vnf
                    # (không gọi thêm KBS annual).
                    addon = self._build_vnf_only_annual_rows(ticker, vnf_annual)
                    if addon:
                        logger.info(
                            f"  {ticker}: + {len(addon)} dòng năm "
                            f"(vnfinancialdata) cho revenue/net_profit/cfo"
                        )
                    history = sorted(
                        history + addon,
                        key=lambda r: (
                            parse_period_label(r["period"]).key()
                            if parse_period_label(r["period"]) else (9999, 9)
                        ),
                    )
                else:
                    logger.info(
                        f"  {ticker}: Không có dữ liệu quý dùng được "
                        f"-> chuyển sang dữ liệu năm"
                    )

                    # ---------- YEAR FALLBACK ----------
                    time.sleep(0.3)
                    df_ratio_y = self._call(finance, "ratio",
                                            ticker, period="year")
                    time.sleep(0.3)
                    df_income_y = self._call(finance, "income_statement",
                                             ticker, period="year")

                    history = self._build_year_history(
                        ticker, df_ratio_y, df_income_y, vnf_annual
                    )

                if not history:
                    logger.info(f"  {ticker}: Không tìm thấy dữ liệu phù hợp")
                    self.diag.add(ticker, "NO_DATA",
                                  "Không có dữ liệu quý lẫn năm dùng được.")
                    return None

                return {
                    "ticker": ticker,
                    "sector": sector,
                    "updated_at": datetime.now().strftime("%Y-%m-%d"),
                    "history": history,
                }

            except Exception as exc:
                message = str(exc).lower()
                is_rate_limit = any(
                    k in message for k in
                    ("rate limit", "exceeded", "too many", "giới hạn", "429")
                )
                if is_rate_limit:
                    logger.warning(
                        f"\n⏳ [Rate Limit] Đụng trần 20 req/phút tại {ticker}. "
                        f"Đang tự động ngủ {self.rate_limit_sleep:.0f}s rồi chạy tiếp..."
                    )
                    time.sleep(self.rate_limit_sleep)
                    continue

                self.diag.add(ticker, "FATAL_ERROR",
                              f"Bỏ qua ticker do lỗi: {exc}")
                logger.error(f"  {ticker}: Lỗi -> {exc}")
                return None

        return None


# ==============================================================
# VALIDATION TRƯỚC KHI GHI FILE
# ==============================================================

def fa_check_record(record: Dict[str, Any]) -> List[str]:
    """
    Kiểm tra một record theo mục 21 của spec.
    Trả về danh sách lỗi (rỗng = hợp lệ).
    """
    errors: List[str] = []
    ticker = record.get("ticker", "?")

    for key in ("ticker", "sector", "updated_at", "history"):
        if key not in record:
            errors.append(f"{ticker}: thiếu key '{key}'")

    history = record.get("history") or []
    if not history:
        errors.append(f"{ticker}: history rỗng")
        return errors

    labels = [row.get("period") for row in history]

    if len(set(labels)) != len(labels):
        errors.append(f"{ticker}: period trùng lặp {labels}")

    for label in labels:
        if not isinstance(label, str):
            errors.append(f"{ticker}: period không phải chuỗi: {label!r}")
            continue
        if "_" in label:
            errors.append(f"{ticker}: period chứa suffix duplicate: {label}")
        if label.count("-Năm") > 1:
            errors.append(f"{ticker}: period lặp hậu tố Năm: {label}")
        if not (QUARTER_COL_RE.match(label)
                or re.match(r"^\d{4}-Năm$", label)):
            errors.append(f"{ticker}: period sai định dạng: {label}")

    parsed = [parse_period_label(label) for label in labels]
    keys = [p.key() for p in parsed if p is not None]
    if keys != sorted(keys):
        errors.append(f"{ticker}: period chưa sắp xếp tăng dần {labels}")

    for row in history:
        missing = [f for f in HISTORY_FIELDS if f not in row]
        if missing:
            errors.append(
                f"{ticker} {row.get('period')}: thiếu field {missing}"
            )
        extra = [f for f in row if f not in HISTORY_FIELDS]
        if extra:
            errors.append(
                f"{ticker} {row.get('period')}: field lạ {extra}"
            )
        if str(row.get("period", "")).endswith("-Năm"):
            for field_name in ("eps_growth_qoq", "revenue_growth_qoq"):
                if row.get(field_name) is not None:
                    errors.append(
                        f"{ticker} {row.get('period')}: kỳ năm không được có "
                        f"{field_name}"
                    )

    return errors


# ==============================================================
# ĐỌC SYMBOLS
# ==============================================================

def fa_read_symbols(path: str) -> List[Tuple[str, str]]:
    """
    Đọc symbols.csv -> [(ticker, sector), ...]

    sector CHỈ lấy từ file. Không suy đoán từ ticker (mục 18 của spec).
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Không tìm thấy file {path}")

    results: List[Tuple[str, str]] = []
    seen = set()
    header_keys = {"symbol", "ticker", "stock", "mã cp", "ma cp", "macp"}

    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        rows = [r for r in reader if r and any(c.strip() for c in r)]

    if not rows:
        return results

    sector_index = 1
    start = 0
    first = [c.strip().lower() for c in rows[0]]

    if first and first[0] in header_keys:
        start = 1
        for index, name in enumerate(first):
            if name in ("sector", "exchange", "san", "sàn", "nhóm ngành",
                        "industry", "group"):
                sector_index = index
                break

    missing_sector = 0

    for row in rows[start:]:
        ticker = row[0].strip().upper()
        if not ticker or ticker.lower() in header_keys:
            continue
        if ticker in seen:
            continue
        seen.add(ticker)

        if len(row) > sector_index and row[sector_index].strip():
            sector = row[sector_index].strip()
        else:
            sector = DEFAULT_SECTOR
            missing_sector += 1

        results.append((ticker, sector))

    if missing_sector:
        logger.warning(
            f"  [WARNING] {missing_sector}/{len(results)} ticker không có "
            f"sector trong {path} -> dùng '{DEFAULT_SECTOR}'. "
            f"KHÔNG suy đoán sector."
        )

    return results


# ==============================================================
# LOAD / SAVE
# ==============================================================

def _load_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        # Không làm mất dữ liệu cũ: backup rồi bắt đầu lại.
        backup = f"{path}.corrupt.{int(time.time())}"
        try:
            os.replace(path, backup)
            logger.error(
                f"Không đọc được {path} ({exc}). Đã backup -> {backup}"
            )
        except Exception:
            logger.error(f"Không đọc được {path}: {exc}")
        return {}


def _atomic_write_json(path: str, payload: Any) -> None:
    """Ghi qua file tạm để không mất dữ liệu nếu process chết giữa chừng."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=4)
    os.replace(temporary, path)


# ==============================================================
# ORCHESTRATION
# ==============================================================

def fa_run_and_save(
    symbols_path: str = "data/symbols.csv",
    output_path: str = "data/financial_data.json",
    diagnostics_path: str = "data/fa_diagnostics.json",
    limit: Optional[int] = LIMIT,
    request_delay: float = 1.5,
    checkpoint_every: int = 5,
    refetch: bool = False,
    only: Optional[List[str]] = None,
    debug_raw: bool = False,
) -> Dict[str, Any]:

    fetcher = FinancialDataFetcher(
        request_delay=request_delay,
        debug_raw=debug_raw,
    )
    vnf_loader = VnfAnnualLoader(fetcher.diag)
    vnf_loader.load()
    fetcher.vnf_loader = vnf_loader

    symbols = fa_read_symbols(symbols_path)

    if only:
        wanted = {s.strip().upper() for s in only}
        symbols = [(t, s) for t, s in symbols if t in wanted]
        # Ticker được chỉ định nhưng không có trong CSV -> vẫn chạy,
        # sector để mặc định vì KHÔNG được suy đoán.
        found = {t for t, _ in symbols}
        for extra in sorted(wanted - found):
            logger.warning(
                f"  [WARNING] {extra} không có trong {symbols_path} "
                f"-> sector = '{DEFAULT_SECTOR}'"
            )
            symbols.append((extra, DEFAULT_SECTOR))

    if limit is not None:
        symbols = symbols[:limit]

    results = _load_json(output_path)
    diagnostics_store = _load_json(diagnostics_path)

    logger.info(
        f"\nBắt đầu thu thập dữ liệu BCTC từ {SOURCE} "
        f"(Tổng: {len(symbols)} mã)"
    )

    total = len(symbols)
    counters = {"ok": 0, "skipped": 0, "failed": 0, "cached": 0}

    for index, (ticker, sector) in enumerate(symbols, start=1):

        if (not refetch
                and ticker in results
                and results[ticker].get("history")):
            logger.info(
                f"[{index}/{total}] {ticker}: Đã có dữ liệu -> bỏ qua"
            )
            counters["cached"] += 1
            continue

        record = fetcher.fa_fetch_ticker(ticker, sector=sector)

        if record is None:
            logger.info(f"[{index}/{total}] {ticker}: Bỏ qua (không có dữ liệu)")
            counters["failed"] += 1
        else:
            errors = fa_check_record(record)
            if errors:
                for error in errors:
                    logger.error(f"  [VALIDATION] {error}")
                    fetcher.diag.add(ticker, "VALIDATION_FAILED", error)
                logger.info(
                    f"[{index}/{total}] {ticker}: KHÔNG lưu - validation thất bại"
                )
                counters["skipped"] += 1
            else:
                results[ticker] = record
                periods = [row["period"] for row in record["history"]]
                logger.info(
                    f"[{index}/{total}] {ticker}: Lưu {len(periods)} kỳ "
                    f"({', '.join(periods)})"
                )
                counters["ok"] += 1

        if index % checkpoint_every == 0:
            _atomic_write_json(output_path, results)
            _atomic_write_json(
                diagnostics_path,
                fetcher.diag.merge_into(diagnostics_store),
            )
            logger.info(f"  -> Đã checkpoint {index}/{total} mã")

        if index < total:
            time.sleep(request_delay)

    _atomic_write_json(output_path, results)
    _atomic_write_json(
        diagnostics_path, fetcher.diag.merge_into(diagnostics_store)
    )

    warning_count = sum(
        1
        for items in fetcher.diag.as_dict().values()
        for item in items
        if item["level"] == "WARNING"
    )

    logger.info("\n" + "=" * 50)
    logger.info(f"Hoàn tất. Tổng ticker trong file: {len(results)}")
    logger.info(
        f"  Lấy mới: {counters['ok']} | Đã có sẵn: {counters['cached']} | "
        f"Không có dữ liệu: {counters['failed']} | "
        f"Lỗi validation: {counters['skipped']}"
    )
    logger.info(f"  Cảnh báo cần xem: {warning_count}")
    logger.info(f"  Dữ liệu    : {output_path}")
    logger.info(f"  Chẩn đoán  : {diagnostics_path}")
    logger.info(f"  Log đầy đủ : data/fa_fetch.log")
    logger.info("=" * 50)

    return results


# ==============================================================
# CLI
# ==============================================================

def _parse_args(argv: List[str]) -> Dict[str, Any]:
    import argparse

    parser = argparse.ArgumentParser(
        description="Thu thập dữ liệu FA từ Vnstock KBS."
    )
    parser.add_argument("--symbols", default="data/symbols.csv")
    parser.add_argument("--output", default="data/financial_data.json")
    parser.add_argument("--diagnostics", default="data/fa_diagnostics.json")
    parser.add_argument(
        "--limit", type=int, default=LIMIT,
        help=f"Số mã tối đa. Mặc định {LIMIT}. Dùng 0 để bỏ giới hạn.",
    )
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument(
        "--refetch", action="store_true",
        help="Lấy lại cả ticker đã có trong JSON.",
    )
    parser.add_argument(
        "--only", default=None,
        help="Danh sách ticker, phân cách bằng dấu phẩy. VD: GVT,MGC,SLD",
    )
    parser.add_argument(
        "--debug-raw", action="store_true",
        help="In toàn bộ DataFrame raw của KBS (dùng để xác minh unit/row).",
    )

    args = parser.parse_args(argv)

    return {
        "symbols_path": args.symbols,
        "output_path": args.output,
        "diagnostics_path": args.diagnostics,
        "limit": None if args.limit == 0 else args.limit,
        "request_delay": args.delay,
        "refetch": args.refetch,
        "only": args.only.split(",") if args.only else None,
        "debug_raw": args.debug_raw,
    }


if __name__ == "__main__":
    setup_logging()
    fa_run_and_save(**_parse_args(sys.argv[1:]))


# ==============================================================
# LIMITATIONS - GIỚI HẠN CỦA NGUỒN KBS (đọc kỹ)
# ==============================================================
#
# 1. Community Edition giới hạn 4 kỳ báo cáo tài chính.
#    => eps_growth_yoy theo QUÝ gần như luôn null. Muốn có, cần 8 quý.
#       Đây là giới hạn của gói dữ liệu, không phải bug của code.
#
# 2. ratio(period="quarter") thường trả ÍT kỳ hơn income_statement và có
#    cột duplicate "_1". Kỳ cũ nhất (VD 2025-Q3) thường không có trong
#    ratio() => pe/pb/roe/debt_equity/net_margin của kỳ đó = null.
#    Đây là null ĐÚNG. Lấy giá trị kỳ khác lấp vào mới là sai.
#
# 3. Unit của roe / net_margin CHƯA được xác nhận là nhất quán giữa các kỳ
#    và giữa các mã. Code này KHÔNG scale. Nếu detector báo
#    UNIT_INCONSISTENCY (trường hợp MGC), hãy chạy:
#        python fetcher_financial.py --only MGC --refetch --debug-raw
#    và đọc giá trị raw trước khi quyết định.
#
# 4. Unit của EPS từ income_statement cũng chưa được xác nhận
#    (PNJ 1,370,000 - quá lớn cho EPS VND/cổ phiếu một quý).
#    Code giữ RAW. Growth không bị ảnh hưởng vì cùng metric, cùng unit.
#    Trước khi dùng eps tuyệt đối cho bộ lọc FA, cần xác minh unit.
#
# 5. sector chỉ đến từ symbols.csv. Nếu CSV thiếu, giá trị là
#    "Chưa phân loại". Không có logic đoán sàn từ mã.
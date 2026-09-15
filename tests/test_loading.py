import pandas as pd
import pytest

from gateway_ranker.checks import DataError
from gateway_ranker.loading import (
    available_before,
    load_dataset,
    load_telemetry,
    normalize_gateway_id,
)
from tests.fixtures import colon_id, make_master, make_meter_reads, make_telemetry, write_data_dir

MONDAY = pd.Timestamp("2026-02-02", tz="UTC")


@pytest.mark.parametrize("raw", ["0A00000000FF", "0a:00:00:00:00:ff", " 0A:00:00:00:00:FF ", "0a00000000ff"])
def test_normalize_gateway_id_accepts_both_formats(raw):
    assert normalize_gateway_id(raw) == "0A00000000FF"


@pytest.mark.parametrize("raw", ["", "0A00000000", "ZZ00000000FF", "0A00000000FF00"])
def test_normalize_gateway_id_rejects_non_ids(raw):
    with pytest.raises(ValueError):
        normalize_gateway_id(raw)


def test_available_before_is_strict_and_needs_utc():
    df = pd.DataFrame({"ts": pd.to_datetime(["2026-02-01 23:00", "2026-02-02 00:00"], utc=True)})
    assert len(available_before(df, "ts", MONDAY)) == 1  # a row exactly at Monday 00:00 is excluded
    with pytest.raises(TypeError):
        available_before(df, "ts", pd.Timestamp("2026-02-02"))


def test_telemetry_duplicates_dropped_and_counted(tmp_path):
    tel = make_telemetry(start="2026-01-01", end="2026-01-02")
    write_data_dir(tmp_path, pd.concat([tel, tel.head(5)]))
    report = {}
    df = load_telemetry(tmp_path, report)
    assert len(df) == len(tel)
    assert report["telemetry_duplicates_dropped"] == 5
    assert report["telemetry_conflicting_duplicates"] == 0


def test_telemetry_months_discovered_not_hard_coded(tmp_path):
    write_data_dir(tmp_path, make_telemetry(start="2026-03-30", end="2026-05-02"))
    report = {}
    load_telemetry(tmp_path, report)
    assert report["telemetry_months"] == ["2026-03", "2026-04", "2026-05"]


def test_telemetry_missing_column_names_the_file(tmp_path):
    write_data_dir(tmp_path, make_telemetry(start="2026-01-01", end="2026-01-02"))
    broken = make_telemetry(start="2026-02-01", end="2026-02-02").drop(columns="reboot_cnt")
    write_data_dir(tmp_path, broken)
    with pytest.raises(DataError, match=r"month=2026-02.*reboot_cnt"):
        load_telemetry(tmp_path)


def test_telemetry_empty_partition_is_an_error(tmp_path):
    tel = make_telemetry(start="2026-01-01", end="2026-01-02")
    write_data_dir(tmp_path, tel)
    (tmp_path / "telemetry" / "month=2026-02").mkdir()
    tel.head(0).to_parquet(tmp_path / "telemetry" / "month=2026-02" / "part-0.parquet", index=False)
    with pytest.raises(DataError, match="no rows"):
        load_telemetry(tmp_path)


def test_no_telemetry_at_all_is_an_error(tmp_path):
    with pytest.raises(DataError, match="no telemetry files"):
        load_telemetry(tmp_path)


def test_master_latin1_and_colon_ids_load(tmp_path):
    write_data_dir(tmp_path, make_telemetry(start="2026-01-01", end="2026-01-02"))
    data = load_dataset(tmp_path)
    assert data.master["site_type"].iloc[0] == "Außenmast"
    assert set(data.master["gateway_id"]) == set(data.telemetry["gateway_id"])


def test_master_bad_date_is_an_error(tmp_path):
    master = make_master()
    master.loc[0, "installed_on"] = "not-a-date"
    write_data_dir(tmp_path, make_telemetry(start="2026-01-01", end="2026-01-02"), master=master)
    with pytest.raises(DataError, match="installed_on"):
        load_dataset(tmp_path)


def test_missing_optional_files_are_reported_not_fatal(tmp_path):
    write_data_dir(tmp_path, make_telemetry(start="2026-01-01", end="2026-01-02"))
    data = load_dataset(tmp_path)
    assert data.meter_reads.empty and data.visits.empty and data.review.empty
    assert "meter_read_success.csv" in data.report["missing_optional_files"]
    data.before(MONDAY)  # cutting empty frames must still work


def test_before_applies_one_cutoff_to_every_file(tmp_path):
    gw = "0A0000000001"
    visits = pd.DataFrame([
        {"visit_id": "V1", "gateway_id": colon_id(gw), "requested_on": "2026-01-20", "visited_on": "2026-01-22",
         "reason_reported": "x", "outcome": "done-before"},
        {"visit_id": "V2", "gateway_id": colon_id(gw), "requested_on": "2026-01-30", "visited_on": "2026-02-04",
         "reason_reported": "x", "outcome": "done-after"},
        {"visit_id": "V3", "gateway_id": colon_id(gw), "requested_on": "2026-02-03", "visited_on": "2026-02-05",
         "reason_reported": "x", "outcome": "requested-after"},
    ])
    review = pd.DataFrame([{"gateway_id": colon_id(gw), "standort": "x", "Kategorie": "Schlecht",
                            "reviewed_on": "2026-02-15", "reviewer": "x", "Bemerkung": "x"}])
    write_data_dir(tmp_path, make_telemetry(start="2026-01-25", end="2026-02-20"),
                   meter_reads=make_meter_reads(weeks=["2026-01-26", "2026-02-02"]), visits=visits, review=review)
    data = load_dataset(tmp_path)

    week1 = data.before(MONDAY)
    assert week1.telemetry["ts"].max() < MONDAY
    assert set(week1.meter_reads["week_start"]) == {pd.Timestamp("2026-01-26", tz="UTC")}  # week W itself is off-limits
    assert week1.visits["visit_id"].tolist() == ["V1", "V2"]
    assert week1.visits["outcome"].isna().tolist() == [False, True]  # V2's outcome is not known yet
    assert week1.review.empty

    assert data.before(pd.Timestamp("2026-02-09", tz="UTC")).review.empty
    assert len(data.before(pd.Timestamp("2026-02-16", tz="UTC")).review) == 1

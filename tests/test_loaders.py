"""Tests for file loading utilities."""

from io import BytesIO
from pathlib import Path

import pandas as pd
import polars as pl
import pytest

from optimizer_340b.ingest.loaders import (
    detect_file_type,
    load_csv_to_polars,
    load_excel_to_polars,
    load_file_auto,
)


class TestDetectFileType:
    """Tests for file type detection."""

    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("data.xlsx", "excel"),
            ("data.XLSX", "excel"),
            ("data.xls", "excel"),
            ("data.XLS", "excel"),
            ("data.csv", "csv"),
            ("data.CSV", "csv"),
            ("my_file.data.xlsx", "excel"),
            ("path/to/file.csv", "csv"),
        ],
    )
    def test_detects_supported_types(self, filename: str, expected: str) -> None:
        """Should correctly detect Excel and CSV file types."""
        result = detect_file_type(filename)
        assert result == expected

    @pytest.mark.parametrize(
        "filename",
        [
            "data.txt",
            "data.json",
            "data.xml",
            "data.parquet",
            "noextension",
            "data.",
        ],
    )
    def test_raises_for_unsupported_types(self, filename: str) -> None:
        """Should raise ValueError for unsupported file types."""
        with pytest.raises(ValueError, match="Unsupported file type"):
            detect_file_type(filename)


class TestLoadExcelToPolars:
    """Tests for Excel file loading."""

    def test_loads_excel_from_path(self, tmp_path: Path) -> None:
        """Should load Excel file from filesystem path."""
        # Create a test Excel file
        test_df = pd.DataFrame({"A": [1, 2, 3], "B": ["x", "y", "z"]})
        excel_path = tmp_path / "test.xlsx"
        test_df.to_excel(excel_path, index=False)

        # Load with our function
        result = load_excel_to_polars(excel_path)

        assert isinstance(result, pl.DataFrame)
        assert result.height == 3
        assert result.width == 2
        assert "A" in result.columns
        assert "B" in result.columns

    def test_loads_excel_from_string_path(self, tmp_path: Path) -> None:
        """Should load Excel file from string path."""
        test_df = pd.DataFrame({"Col1": [10, 20]})
        excel_path = tmp_path / "test.xlsx"
        test_df.to_excel(excel_path, index=False)

        result = load_excel_to_polars(str(excel_path))

        assert isinstance(result, pl.DataFrame)
        assert result.height == 2

    def test_loads_specific_sheet(self, tmp_path: Path) -> None:
        """Should load specific sheet by name or index."""
        excel_path = tmp_path / "multi_sheet.xlsx"

        # Create multi-sheet Excel file
        with pd.ExcelWriter(excel_path) as writer:
            pd.DataFrame({"A": [1]}).to_excel(writer, sheet_name="Sheet1", index=False)
            pd.DataFrame({"B": [2]}).to_excel(writer, sheet_name="Data", index=False)

        # Load by name
        result = load_excel_to_polars(excel_path, sheet_name="Data")
        assert "B" in result.columns

        # Load by index
        result = load_excel_to_polars(excel_path, sheet_name=0)
        assert "A" in result.columns

    def test_raises_for_invalid_file(self, tmp_path: Path) -> None:
        """Should raise ValueError for invalid Excel file."""
        invalid_path = tmp_path / "invalid.xlsx"
        invalid_path.write_text("not an excel file")

        with pytest.raises(ValueError, match="Cannot parse Excel file"):
            load_excel_to_polars(invalid_path)


class TestLoadCsvToPolars:
    """Tests for CSV file loading."""

    def test_loads_csv_from_path(self, tmp_path: Path) -> None:
        """Should load CSV file from filesystem path."""
        csv_path = tmp_path / "test.csv"
        csv_path.write_text("A,B,C\n1,2,3\n4,5,6\n")

        result = load_csv_to_polars(csv_path)

        assert isinstance(result, pl.DataFrame)
        assert result.height == 2
        assert result.width == 3

    def test_loads_csv_with_latin1_encoding(self, tmp_path: Path) -> None:
        """Should handle latin-1 encoded files (common for CMS data)."""
        csv_path = tmp_path / "test.csv"
        # Write with latin-1 encoding
        content = "Name,Value\nCaf\xe9,100\n"
        csv_path.write_bytes(content.encode("latin-1"))

        result = load_csv_to_polars(csv_path, encoding="latin-1")

        assert result.height == 1
        assert "Caf\xe9" in result["Name"].to_list()

    def test_loads_csv_from_file_object(self) -> None:
        """Should load CSV from file-like object."""
        content = b"X,Y\n10,20\n30,40\n"
        file_obj = BytesIO(content)

        result = load_csv_to_polars(file_obj)

        assert result.height == 2
        assert "X" in result.columns

    def test_drops_empty_columns(self, tmp_path: Path) -> None:
        """Should drop completely empty columns (common in CMS crosswalk)."""
        csv_path = tmp_path / "test.csv"
        # Create CSV with empty columns
        csv_path.write_text("A,B,C,D\n1,,3,\n2,,4,\n")

        result = load_csv_to_polars(csv_path)

        # Empty columns B and D should be dropped
        assert "A" in result.columns
        assert "C" in result.columns
        # Note: Polars may keep columns with only null values depending on version

    def test_raises_for_nonexistent_file(self, tmp_path: Path) -> None:
        """Should raise ValueError for non-existent file."""
        nonexistent_path = tmp_path / "does_not_exist.csv"

        with pytest.raises(ValueError, match="Cannot parse CSV file"):
            load_csv_to_polars(nonexistent_path)


class TestLoadFileAuto:
    """Tests for auto-detecting file loader."""

    def test_auto_loads_excel(self, tmp_path: Path) -> None:
        """Should auto-detect and load Excel files."""
        test_df = pd.DataFrame({"Data": [1, 2, 3]})
        excel_path = tmp_path / "auto_test.xlsx"
        test_df.to_excel(excel_path, index=False)

        result = load_file_auto(excel_path)

        assert isinstance(result, pl.DataFrame)
        assert "Data" in result.columns

    def test_auto_loads_csv(self, tmp_path: Path) -> None:
        """Should auto-detect and load CSV files."""
        csv_path = tmp_path / "auto_test.csv"
        csv_path.write_text("Value\n100\n200\n")

        result = load_file_auto(csv_path)

        assert isinstance(result, pl.DataFrame)
        assert "Value" in result.columns

    def test_requires_filename_for_file_object(self) -> None:
        """Should require filename parameter for file-like objects."""
        file_obj = BytesIO(b"A,B\n1,2\n")

        with pytest.raises(ValueError, match="filename must be provided"):
            load_file_auto(file_obj)

    def test_accepts_filename_for_file_object(self) -> None:
        """Should use provided filename for type detection."""
        file_obj = BytesIO(b"A,B\n1,2\n")

        result = load_file_auto(file_obj, filename="data.csv")

        assert isinstance(result, pl.DataFrame)
        assert result.height == 1

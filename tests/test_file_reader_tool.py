from core.tools.file_reader_tool import FileReaderTool

TOOL = FileReaderTool(base_dir="tasks/sample_data/invoices")


def test_find_existing_company():
    obs = TOOL.execute({"action": "find", "company": "Company X"})
    assert obs.success
    assert any("company_x" in m.lower() for m in obs.structured_data["matches"])


def test_find_missing_company():
    obs = TOOL.execute({"action": "find", "company": "Nonexistent Corp"})
    assert not obs.success
    assert obs.error_type == "not_found"


def test_extract_clean_invoice():
    obs = TOOL.execute({"action": "extract", "path": "tasks/sample_data/invoices/company_x_clean.txt"})
    assert obs.success
    assert obs.structured_data["company"] == "Company X"
    assert obs.structured_data["amount"] == 42000.0
    assert obs.structured_data["due_date"] == "2025-11-15"


def test_extract_missing_due_date():
    obs = TOOL.execute({"action": "extract", "path": "tasks/sample_data/invoices/company_y_missing_duedate.txt"})
    assert not obs.success
    assert obs.error_type == "missing_field"
    assert "due_date" in obs.error_message


def test_extract_renamed_field_still_parses():
    obs = TOOL.execute({"action": "extract", "path": "tasks/sample_data/invoices/company_z_renamed_field.txt"})
    assert obs.success
    assert obs.structured_data["due_date"] == "2025-10-20"


def test_extract_corrupted_amount():
    obs = TOOL.execute({"action": "extract", "path": "tasks/sample_data/invoices/company_w_corrupted.txt"})
    assert not obs.success
    assert obs.error_type == "invalid_value"
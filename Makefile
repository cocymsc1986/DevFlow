.PHONY: test test-qa

test:
	cd backend && python -m pytest

test-qa:
	cd backend && python -m pytest test_qa_worker.py -v

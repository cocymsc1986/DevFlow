.PHONY: qa-image qa-image-clean

QA_IMAGE ?= devflow/qa-runner:latest

qa-image:
	docker build -t $(QA_IMAGE) backend/qa/images

qa-image-clean:
	docker rmi $(QA_IMAGE) || true

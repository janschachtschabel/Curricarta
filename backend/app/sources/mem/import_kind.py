"""The job that imports a MEM plan (app/sources/mem/import_job.py): its kind and stages, apart from the
job, so that the API and the cost estimate name them without importing the pipeline - as
app/pipeline/extraction.py keeps the extraction's."""

KIND = "extract.mem_import"
STAGES = ["IM", "X5"]

#!/bin/bash

# JobSeekerAgency daily job search script
# To schedule this to run daily at 3pm, add this line to your crontab:
#   crontab -e
#   0 15 * * * /Users/giorgiotamo/Desktop/GT/Programming/Lavoro/GitHub/JobSeekerAgency/runchronjob.sh >> /Users/giorgiotamo/Desktop/GT/Programming/Lavoro/GitHub/JobSeekerAgency/logs/cron.log 2>&1

# type "date" in command line to check current date and time
# type "crontab -l" to list your cron jobs

echo "========================================"
echo "Job started at: $(date)"
echo "========================================"

# Initialize and activate conda environment
source ~/anaconda3/etc/profile.d/conda.sh
conda activate llms_rag

# Run the job search script
python "/Users/giorgiotamo/Desktop/GT/Programming/Lavoro/GitHub/JobSeekerAgency/python/run.py"

echo "========================================"
echo "Job finished at: $(date)"
echo "========================================"

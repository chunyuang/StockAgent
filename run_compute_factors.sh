#!/bin/bash
start_date=$1
end_date=$2

python scripts/compute_factors.py $start_date $end_date

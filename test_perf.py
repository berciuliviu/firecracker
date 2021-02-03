import os
import subprocess
import re
import json

LOG_LINE_REGEX = "-&%-.*-&%-"
CONFIGS = [
    # [2, 128],
    # [2, 256],
    # [2, 512],
    # [2, 1024],
    [1, 5307],
    [2, 5307],
    [3, 5307],
    # [4, 7076],
    # [5, 8845],
    # [6, 10240],
    ]

# Create dictionary that tracks performance metrics
# The metrics need to have the same name as the ones added in Firecracker
def get_perf_dict():
    with open("performance_fields.json") as json_file:
        perf_dict = json.load(json_file)

    return perf_dict

def parse_output(log, perf_dict):
    matches = re.findall(LOG_LINE_REGEX, log)
    for match in matches:
        # print(match)
        parts = match.split(" ")
        # print(parts)
        if (parts[1] not in perf_dict):
            perf_dict[parts[1]] = [ int(parts[2]) ]
        else:
            perf_dict[parts[1]].insert(0, int(parts[2]))

import numpy as np

def format_perf_dict(perf_dict, vcpu_count, mem_size_mib):
    print("--------- RESULTS for {} VCPUs and {} MEM_SIZE - METRIC - P50 - P90 -----------".format(vcpu_count, mem_size_mib))
    for key in perf_dict:
        values = np.array(perf_dict[key])
        p50 = np.percentile(values, 50)
        p90 = np.percentile(values, 90)

        print("{} - {} - {}".format(key,p50,p90))


def main():
    for config in CONFIGS:
        perf_dict = get_perf_dict()
        vcpu_count = config[0]
        mem_size_mib = config[1]

        result = subprocess.run(["./tools/devtool test -- integration_tests/functional/test_lambda_statistics.py --vcpu_cnt {} --mem_size {}".format(vcpu_count, mem_size_mib)],shell=True, stdout=subprocess.PIPE)
        log = result.stdout.decode('ascii')
        # print(log)
        parse_output(log, perf_dict)
        #print(perf_dict)
        format_perf_dict(perf_dict, vcpu_count, mem_size_mib)
        #print(perf_dict)

if __name__ == "__main__":
    main()

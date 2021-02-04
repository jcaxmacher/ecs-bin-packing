#!/bin/env python3
"""
This script examines all ECS clusters and connected tasks, writing out two CSV file for each cluster.

One report details the container instance resources (CPU, Mem), associated capacity provider, managed
scaling details, autoscaling group ARN, and autoscaling group scaling policies.

The other report details the tasks running in the cluster including CPU and Memory reservations for each task,
ECS service that is linked to the task, and Max/Average CloudWatch metrics for CPU/Memory utilization for each
ECS service.
"""
import os
import datetime as dt
import json
import csv
import sys
import functools

import boto3
import binpacking


cw = boto3.client("cloudwatch")
ecs = boto3.client("ecs")
asg = boto3.client("autoscaling")


def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def get_container_instance_details(cluster_name):
    """Get select details from the container instances in a cluster."""
    keys = set()
    paginator = ecs.get_paginator("list_container_instances")
    instances = []
    for response in paginator.paginate(cluster=cluster_name, status="ACTIVE"):
        instances.extend(response["containerInstanceArns"])
    details = []
    # DescribeContainerInstances can get details on up to 100 container instances per API call
    for group in chunks(instances, 100):
        response = ecs.describe_container_instances(
            cluster=cluster_name, containerInstances=group
        )
        for instance in response["containerInstances"]:
            print(f"Gathering details for container instance {instance['containerInstanceArn']}")
            resources = {}
            # Pull out CPU and Memory resources (other details like GPUs exist but are not examined
            for resource in instance["registeredResources"]:
                if resource["name"] == "CPU":
                    resources["cpu"] = resource["integerValue"]
                elif resource["name"] == "MEMORY":
                    resources["memory"] = resource["integerValue"]
            detail = {
                "cluster": cluster_name,
                "instanceId": instance["ec2InstanceId"],
                "status": instance["status"],
                "cpu": resources["cpu"],
                "memory": resources["memory"],
            }
            # If a capacity provider is associated with the instance get the details
            if instance.get("capacityProviderName"):
                cap_provider_details = get_cap_provider_details(
                    instance["capacityProviderName"]
                )
                detail.update(cap_provider_details)
                detail.update(
                    {"capacityProviderName": instance["capacityProviderName"]}
                )
            details.append(detail)
            keys.update(list(detail.keys()))
    return keys, details


def get_task_details(cluster_name):
    """Get select task details for the cluster."""
    keys = set()
    paginator = ecs.get_paginator("list_tasks")
    tasks = []
    for response in paginator.paginate(cluster=cluster_name, desiredStatus="RUNNING"):
        tasks.extend(response["taskArns"])
    details = []
    # DescribeTasks can get details on up to 100 tasks per API call
    for group in chunks(tasks, 100):
        response = ecs.describe_tasks(cluster=cluster_name, tasks=group)
        for task in response["tasks"]:
            print(f"Gathering details for task {task['taskArn']}")
            mem_type = None
            cpu_type = None
            container_reserved_memory = 0
            container_reserved_cpu = 0
            containers = []
            for container in task["containers"]:
                # Is there a memory reservation (i.e., soft limit)
                if container.get("memoryReservation") and container[
                    "memoryReservation"
                ] not in (0, "0"):
                    container_reserved_memory += int(container["memoryReservation"])
                # If not, let's check the memory (i.e., hard limit)
                elif container.get("memory") and container["memory"] not in (0, "0"):
                    container_reserved_memory += int(container["memory"])
                container_reserved_cpu += int(container.get("cpu", "0"))
                containers.append(
                    {
                        "cpu": container.get("cpu", "empty"),
                        "memory": container.get("memory", "empty"),
                        "memoryReservation": container.get(
                            "memoryReservation", "empty"
                        ),
                    }
                )
            # Task-level settings take precedence
            if task.get("memory") and task["memory"] not in (0, "0"):
                mem_allocation = int(task["memory"])
                mem_type = "TASK"
            else:
                mem_allocation = container_reserved_memory
                mem_type = "CONTAINERS"
            # Task-level settings take precedence
            if task.get("cpu") and task["cpu"] not in (0, "0"):
                cpu_allocation = int(task["cpu"])
                cpu_type = "TASK"
            else:
                cpu_allocation = container_reserved_cpu
                cpu_type = "CONTAINERS"
            detail = {
                "cluster": cluster_name,
                "taskArn": task["taskArn"],
                "taskDefinitionArn": task["taskDefinitionArn"],
                "launchType": task["launchType"],
                "desiredStatus": task["desiredStatus"],
                "lastStatus": task["lastStatus"],
                "cpuAllocation": cpu_allocation,
                "cpuType": cpu_type,
                "memoryAllocation": mem_allocation,
                "memoryType": mem_type,
                "containers": containers,
                "group": task["group"],
            }
            # Get associated service details if the task group is a service
            if detail["group"].startswith("service:"):
                service = detail["group"][8:]
                service_detail = get_service_details(cluster_name, service)
                detail.update(service_detail)
            details.append(detail)
            keys.update(list(detail.keys()))
    return keys, details


def get_clusters():
    """Get a list of ECS cluster ARNs."""
    paginator = ecs.get_paginator("list_clusters")
    clusters = []
    for response in paginator.paginate():
        clusters.extend(response["clusterArns"])
    return clusters


# Use memoization to limit metric get api calls
@functools.lru_cache(maxsize=2048)
def get_service_details(cluster, service):
    """Get ECS service details including placement details and utilization metrics."""
    print(f"Gathering details for service {service}")
    cluster_name = cluster.split("/")[-1]
    response = ecs.describe_services(cluster=cluster, services=[service])
    results = {
        "placementStrategy": response["services"][0]["placementStrategy"],
        "placementConstraints": response["services"][0]["placementConstraints"],
        "schedulingStrategy": response["services"][0]["schedulingStrategy"],
    }
    end_time = dt.datetime.utcnow()
    start_time = end_time - dt.timedelta(days=7)
    period = int((end_time - start_time).total_seconds())
    response = cw.get_metric_statistics(
        Namespace="AWS/ECS",
        MetricName="MemoryUtilization",
        Dimensions=[
            {"Name": "ClusterName", "Value": cluster_name},
            {"Name": "ServiceName", "Value": service},
        ],
        StartTime=start_time,
        EndTime=end_time,
        Period=period,
        Statistics=["Average", "Maximum"],
        Unit="Percent",
    )
    results.update(
        {
            "memoryAverage": response["Datapoints"][0]["Average"],
            "memoryMaximum": response["Datapoints"][0]["Maximum"],
        }
    )
    response = cw.get_metric_statistics(
        Namespace="AWS/ECS",
        MetricName="CPUUtilization",
        Dimensions=[
            {"Name": "ClusterName", "Value": cluster_name},
            {"Name": "ServiceName", "Value": service},
        ],
        StartTime=start_time,
        EndTime=end_time,
        Period=period,
        Statistics=["Average", "Maximum"],
        Unit="Percent",
    )
    results.update(
        {
            "cpuAverage": response["Datapoints"][0]["Average"],
            "cpuMaximum": response["Datapoints"][0]["Maximum"],
        }
    )
    return results


def get_cap_provider_details(cap_provider_name):
    """Get capacity provider details including managed scaling details, ASG,
    and scaling policies."""
    response = ecs.describe_capacity_providers(capacityProviders=[cap_provider_name])
    # Only one capacity provider and autoscaling group supported/examined
    asg_arn = response["capacityProviders"][0]["autoScalingGroupProvider"][
        "autoScalingGroupArn"
    ]
    asg_response = asg.describe_auto_scaling_groups(
        AutoScalingGroupNames=[asg_arn.split("/")[-1]]
    )
    pol_response = asg.describe_policies(AutoScalingGroupName=asg_arn.split("/")[-1])
    return {
        "managedScaling": json.dumps(
            response["capacityProviders"][0]["autoScalingGroupProvider"][
                "managedScaling"
            ],
            indent=4,
        ),
        "asgArn": asg_arn,
        "asgMetrics": asg_response["AutoScalingGroups"][0]["EnabledMetrics"],
        "scalingPolicies": json.dumps(
            [
                {
                    "policyName": p["PolicyName"],
                    "targetTrackingConfiguration": p.get("TargetTrackingConfiguration"),
                }
                for p in pol_response["ScalingPolicies"]
            ],
            indent=4,
        ),
    }


def main():
    """Main loop and report writer."""
    try:
        # Make sure output folder exists
        os.makedirs("output")
    except FileExistsError:
        pass
    clusters = get_clusters()
    for cluster in clusters:
        cn = cluster.split("/")[-1]
        print(f"# Gathering data for cluster {cluster}")
        keys, cid = get_container_instance_details(cluster)
        cluster_name = cluster.split("/")[1]
        with open(f"output/{cluster_name}.csv", "w") as f:
            cw = csv.DictWriter(f, fieldnames=sorted(list(keys)))
            cw.writeheader()
            cw.writerows(cid)
        keys, tasks = get_task_details(cluster)
        with open(f"output/{cluster_name}--tasks.csv", "w") as f:
            cw = csv.DictWriter(f, fieldnames=sorted(list(keys)))
            cw.writeheader()
            cw.writerows(tasks)


if __name__ == "__main__":
    main()

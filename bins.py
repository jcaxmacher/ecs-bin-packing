import json
import csv
import sys

import boto3
import binpacking


def old():
    with open('task-memory.txt', 'r') as f:
        mems = f.readlines()

    mems = [int(m.strip()) for m in mems]
    bins = binpacking.to_constant_volume(mems, int(sys.argv[1]))
    print(f'{len(bins)} instances needed')


def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def get_container_instance_details(cluster_name):
    keys = set()
    ecs = boto3.client('ecs')
    paginator = ecs.get_paginator('list_container_instances')
    instances = []
    for response in paginator.paginate(cluster=cluster_name, status='ACTIVE'):
        instances.extend(response['containerInstanceArns'])
    details = []
    for group in chunks(instances, 100):
        response = ecs.describe_container_instances(cluster=cluster_name, containerInstances=group)
        for instance in response['containerInstances']:
            resources = {}
            for resource in instance['registeredResources']:
                if resource['name'] == 'CPU':
                    resources['cpu'] = resource['integerValue']
                elif resource['name'] == 'MEMORY':
                    resources['memory'] = resource['integerValue']
            detail = {
                'cluster': cluster_name,
                'instanceId': instance['ec2InstanceId'],
                'status': instance['status'],
                'cpu': resources['cpu'],
                'memory': resources['memory']
            }
            if instance.get('capacityProviderName'):
                cap_provider_details = get_cap_provider_details(instance['capacityProviderName'])
                detail.update(cap_provider_details)
                detail.update({'capacityProviderName': instance['capacityProviderName']})
            details.append(detail)
            keys.update(list(detail.keys()))
    return keys, details


def get_task_details(cluster_name):
    keys = set()
    ecs = boto3.client('ecs')
    paginator = ecs.get_paginator('list_tasks')
    tasks = []
    for response in paginator.paginate(cluster=cluster_name, desiredStatus='RUNNING'):
        tasks.extend(response['taskArns'])
    details = []
    for group in chunks(tasks, 100):
        response = ecs.describe_tasks(cluster=cluster_name, tasks=group)
        for task in response['tasks']:
            mem_type = None
            cpu_type = None
            container_reserved_memory = 0
            container_reserved_cpu = 0
            containers = []
            for container in task['containers']:
                # Is there a memory reservation (i.e., soft limit)
                if container.get('memoryReservation') and container['memoryReservation'] not in (0, '0'):
                    container_reserved_memory += int(container['memoryReservation'])
                # If not, let's check the memory (i.e., hard limit)
                elif container.get('memory') and container['memory'] not in (0, '0'):
                    container_reserved_memory += int(container['memory'])
                container_reserved_cpu += int(container.get('cpu', '0'))
                containers.append({
                    'cpu': container.get('cpu', 'empty'),
                    'memory': container.get('memory', 'empty'),
                    'memoryReservation': container.get('memoryReservation', 'empty')
                })
            # Task-level settings take precedence
            if task.get('memory') and task['memory'] not in (0, '0'):
                mem_allocation = int(task['memory'])
                mem_type = 'TASK'
            else:
                mem_allocation = container_reserved_memory
                mem_type = 'CONTAINERS'
            # Task-level settings take precedence
            if task.get('cpu') and task['cpu'] not in (0, '0'):
                cpu_allocation = int(task['cpu'])
                cpu_type = 'TASK'
            else:
                cpu_allocation = container_reserved_cpu
                cpu_type = 'CONTAINERS'
            detail = {
                'cluster': cluster_name,
                'taskArn': task['taskArn'],
                'taskDefinitionArn': task['taskDefinitionArn'],
                'launchType': task['launchType'],
                'desiredStatus': task['desiredStatus'],
                'lastStatus': task['lastStatus'],
                'cpuAllocation': cpu_allocation,
                'cpuType': cpu_type,
                'memoryAllocation': mem_allocation,
                'memoryType': mem_type,
                'containers': containers,
                'group': task['group']
            }
            if detail['group'].startswith('service:'):
                service = detail['group'][8:]
                service_detail = get_service_details(cluster_name, service)
                detail.update(service_detail)
            details.append(detail)
            keys.update(list(detail.keys()))
    return keys, details


def get_clusters():
    ecs = boto3.client('ecs')
    paginator = ecs.get_paginator('list_clusters')
    clusters = []
    for response in paginator.paginate():
        clusters.extend(response['clusterArns'])
    return clusters


def get_service_details(cluster, service):
    ecs = boto3.client('ecs')
    response = ecs.describe_services(cluster=cluster, services=[service])
    return {
        'placementStrategy': response['services'][0]['placementStrategy'],
        'placementConstraints': response['services'][0]['placementConstraints'],
        'schedulingStrategy': response['services'][0]['schedulingStrategy']
    }


def get_cap_provider_details(cap_provider_name):
    ecs = boto3.client('ecs')
    response = ecs.describe_capacity_providers(capacityProviders=[cap_provider_name])
    asg_arn = response['capacityProviders'][0]['autoScalingGroupProvider']['autoScalingGroupArn']
    print(asg_arn)
    asg = boto3.client('autoscaling')
    asg_response = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_arn.split('/')[-1]])
    print(asg_response)
    pol_response = asg.describe_policies(AutoScalingGroupName=asg_arn.split('/')[-1])
    return {
        'managedScaling': json.dumps(response['capacityProviders'][0]['autoScalingGroupProvider']['managedScaling'], indent=4),
        'asgArn': asg_arn,
        'asgMetrics': asg_response['AutoScalingGroups'][0]['EnabledMetrics'],
        'scalingPolicies': json.dumps([
            {'policyName': p['PolicyName'], 'targetTrackingConfiguration': p.get('TargetTrackingConfiguration')}
            for p in pol_response['ScalingPolicies']
        ], indent=4)
    }


def main():
    clusters = get_clusters()
    for cluster in clusters:
        keys, cid = get_container_instance_details(cluster)
        cluster_name = cluster.split('/')[1]
        with open(f'{cluster_name}.csv', 'w') as f:
            cw = csv.DictWriter(f, fieldnames=sorted(list(keys)))
            cw.writeheader()
            cw.writerows(cid)
        keys, tasks = get_task_details(cluster)
        with open(f'{cluster_name}--tasks.csv', 'w') as f:
            cw = csv.DictWriter(f, fieldnames=sorted(list(keys)))
            cw.writeheader()
            cw.writerows(tasks)


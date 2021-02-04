# Basic execution

```
$ python3 -m venv venv
$ source venv/bin/activate
$ pip install -r requirements.txt
$ python ecs-details.py
# Gathering data for cluster arn:aws:ecs:us-east-1:123412341234:cluster/test
Gathering details for container instance arn:aws:ecs:us-east-1:0123412341234:container-instance/test/40f451fb34ff489d9c2cb11c94b0f9e5
Gathering details for task arn:aws:ecs:us-east-1:123412341234:task/test/172a94e97c8f48fb99303c2d36ee177c
Gathering details for service EcsService-1K84EKRXR8QB8
# Gathering data for cluster arn:aws:ecs:us-east-1:123412341234:cluster/test2
Gathering details for task arn:aws:ecs:us-east-1:123412341234:task/test2/ea919cbfe2674a83819ab41c51320af4
Gathering details for service EcsServiceFargate-bTFhWk7V5aeU
# Gathering data for cluster arn:aws:ecs:us-east-1:123412341234:cluster/test3
Gathering details for task arn:aws:ecs:us-east-1:123412341234:task/test3/854442d7377c46009bd6d7643dfe93d1
Gathering details for service EcsServiceFargate-u6ujLLmiTX5x
```

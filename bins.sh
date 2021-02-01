#!/bin/bash

cluster_name=$1

echo "Performing calculations for cluster $cluster_name"

echo "Checking container instance memory size"
for inst in $(aws ecs describe-container-instances --cluster $cluster_name --container-instances $(aws ecs list-container-instances --cluster $cluster_name --query containerInstanceArns --output text) --query "containerInstances[].registeredResources[?name=='MEMORY'].integerValue" --output text )
do
  echo $inst >> container-instance-memory.txt
done
ct=$(wc -l container-instance-memory.txt | cut -d ' ' -f1)
size=$(awk '{s+=$1}END{print "ave:",s/NR}' container-instance-memory.txt | cut -d' ' -f2)
echo "Current instance count = $ct"
echo "Average memory = $size"

echo "Getting cluster task arns"
for arn in $(aws ecs list-tasks --cluster $cluster_name --query taskArns --output text); do echo $arn; done | split -l 100
 
echo "Querying task memory limits"
for fn in $(ls x*)
do
  #echo "Reading file $fn"
  #aws --output text ecs describe-tasks --cluster apps-qa-linux --query "tasks[].{containerMemoryReservation: containers[].memoryReservation | join(',',@), containerMemory: containers[].memory | join(',',@), taskMemory: memory}" --tasks $(cat $fn) >> 
  for mem in $(aws --output text ecs describe-tasks --cluster $cluster_name --query "tasks[].memory" --tasks $(cat $fn))
  do
    echo $mem >> task-memory.txt
  done
done
tct=$(wc -l task-memory.txt | cut -d ' ' -f1)
tsize=$(awk '{s+=$1}END{print s}' task-memory.txt)
echo "Current task count = $tct"
echo "Total memory reserved = $tsize"

python bins.py $size

rm task-memory.txt
rm container-instance-memory.txt
rm x*

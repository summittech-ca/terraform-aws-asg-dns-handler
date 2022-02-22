import json
import logging
import boto3
import sys
import os
import socket

logger = logging.getLogger()
logger.setLevel(logging.INFO)

autoscaling = boto3.client('autoscaling')
ec2 = boto3.client('ec2')
route53 = boto3.client('route53')

HOSTNAME_TAG_NAME_PUBLIC = os.environ['hostname_tag_name_public']
HOSTNAME_TAG_NAME_PRIVATE = os.environ['hostname_tag_name_private']

LIFECYCLE_KEY = "LifecycleHookName"
ASG_KEY = "AutoScalingGroupName"

# Fetches IP of an instance via EC2 API
def fetch_ip_from_ec2(instance_id, fetch_public_ip):
    logger.info("Fetching IP for instance-id: %s", instance_id)
    ip_address = None
    filter = [{ 'Name': "instance-state-name", 'Values': ["running"] }]
    ec2_response = ec2.describe_instances(Filters=filter, InstanceIds=[instance_id])['Reservations'][0]['Instances'][0]
    if ec2_response['State']['Name'] == 'running':
      if fetch_public_ip:
        try:
          ip_address = ec2_response['PublicIpAddress']
          logger.info("Found public IP for instance-id %s: %s", instance_id, ip_address)
        except:
          try:
            logger.info("Fetching public IP from PublicDnsName %s: %s", instance_id, ec2_response['PublicDnsName'])
            addressInfo = socket.getaddrinfo(ec2_response['PublicDnsName'], 80, family=socket.AF_INET, proto=socket.IPPROTO_TCP)
            ip_address = addressInfo[0][4][0]
            logger.info("Found public IP for instance-id %s: %s", instance_id, ip_address)
          except:
            logger.info("No public IP for instance-id %s: %s", instance_id, ip_address)
      else:
        try:
          ip_address = ec2_response['PrivateIpAddress']
          logger.info("Found private IP for instance-id %s: %s", instance_id, ip_address)
        except:
          logger.info("No private IP for instance-id %s: %s", instance_id, ip_address)

    return ip_address

# Fetches IP of an instance via route53 API
def fetch_rrs_from_route53(hostname, zone_id):
    logger.info("Fetching RRs for hostname: %s", hostname)
    result = False
    try:
      result = route53.list_resource_record_sets(
          HostedZoneId=zone_id,
          StartRecordName=hostname,
          StartRecordType='A',
          MaxItems='250'
      )
      # This API is braindead, and gladly returns you records that have NOTHING to do
      # with what you requested.
      # [INFO] 2022-02-07T19:38:01.939Z 66d49cc3-2990-4277-98ae-2816c80ea411 Found RRs
      #       for hostname pub.ca-central-1a.priv.odience.org:
      #       {'Name': 'rep.ca-central-1a.priv.odience.org.',
      #       'Type': 'A', 'TTL': 15, 'ResourceRecords': [{'Value': '10.10.64.24'}]}

      # Because this API call is clinically retarded, we need to filter on our own
      if ('Name' in result) and (result['Name'] == hostname):
        rrs = result['ResourceRecordSets'][0]
        logger.info("Found RRs for hostname %s: %s", hostname, rrs)
        return rrs
      else:
        logger.warn("Discarding nonsensical junk response due to hostname mismatch %s: %s", hostname, result)
        return []
    except IndexError:
      logger.warn("IndexError on result %s", result)
      return False

# Fetches relevant tags from ASG
# Returns tuple of hostname_pattern, zone_id
def fetch_tag_metadata(asg_name, TAG_NAME):
    logger.info("Fetching tags for ASG: %s, TAG_NAME: %s", asg_name, TAG_NAME)

    if (TAG_NAME == ""):
      return ""

    tag_value = autoscaling.describe_tags(
        Filters=[
            {'Name': 'auto-scaling-group','Values': [asg_name]},
            {'Name': 'key','Values': [TAG_NAME]}
        ],
        MaxRecords=1
    )['Tags'][0]['Value']

    logger.info("Found tags for ASG %s: %s", asg_name, tag_value)

    return tag_value.split("@")

# Builds a hostname according to pattern
def build_hostname(hostname_pattern, instance_id):
    return hostname_pattern.replace('#instanceid', instance_id)

# Updates the name tag of an instance
def update_name_tag(instance_id, hostname):
    tag_name = hostname.split('.')[0]
    logger.info("Updating name tag for instance-id %s with: %s", instance_id, tag_name)
    ec2.create_tags(
        Resources = [
            instance_id
        ],
        Tags = [
            {
                'Key': 'Name',
                'Value': tag_name
            }
        ]
    )

# Updates a Route53 record
def update_record(zone_id, ips, hostname):
    if len(ips) == 0:
      logger.info("No ips found, deleting DNS record")
      rrs = fetch_rrs_from_route53(hostname, zone_id)
      if (rrs == False) or (rrs == []):
        logger.info("Record for %s in %s does not exist, and no IPs found (noop)", hostname, zone_id)
      else:
        logger.info("Deleting record for %s -> %s in %s", hostname, rrs, zone_id)
        route53.change_resource_record_sets(
            HostedZoneId=zone_id,
            ChangeBatch={
                'Changes': [
                    {
                        'Action': 'DELETE',
                        'ResourceRecordSet': rrs
                    }
                ]
            }
        )
    else:
      operation = 'UPSERT'
      logger.info("Changing record with %s for %s -> %s in %s", operation, hostname, ips, zone_id)
      route53.change_resource_record_sets(
          HostedZoneId=zone_id,
          ChangeBatch={
              'Changes': [
                  {
                      'Action': operation,
                      'ResourceRecordSet': {
                          'Name': hostname,
                          'Type': 'A',
                          'TTL': 15,
                          'ResourceRecords': ips
                      }
                  }
              ]
          }
      )

def process_asg(auto_scaling_group_name, hostname, ignore_instance, fetch_public_ip):
  # Iterate through the instance group: Put IP addresses into a list and update the instance names to match the group.
  # ignore_instance should only be provided if we are terminating an instance.
  ips = []
  # IP's is a list of dictionaries [{'Value': ipAddr1},{'Value': ipAddr2}] eg [{'Value':'127.0.0.1'}]
  if ignore_instance is None:
    logger.info("Processing ASG %s", auto_scaling_group_name)
  else:
    logger.info("Ignoring instance-id %s while Processing ASG %s", ignore_instance, auto_scaling_group_name)
  for instance in autoscaling.describe_auto_scaling_groups(AutoScalingGroupNames=[auto_scaling_group_name])['AutoScalingGroups'][0]['Instances']:
    if ignore_instance != instance['InstanceId']:
      ipAddr = fetch_ip_from_ec2(instance['InstanceId'], fetch_public_ip)
      if ipAddr is not None:
        ips.append({'Value': ipAddr})
        # update_name_tag(instance['InstanceId'], hostname) # This is stupid logic we don't want
  return ips


# Processes a scaling event
# Builds a hostname from tag metadata, fetches a IP, and updates records accordingly
def process_message(message):
    if 'LifecycleTransition' not in message:
        logger.info("Processing %s event", message['Event'])
        return
    logger.info("Processing %s event", message['LifecycleTransition'])

    if message['LifecycleTransition'] not in ("autoscaling:EC2_INSTANCE_LAUNCHING","autoscaling:EC2_INSTANCE_TERMINATING", "autoscaling:EC2_INSTANCE_LAUNCH_ERROR"):
      logger.error("Encountered unknown event type: %s", message['LifecycleTransition'])

    asg_name    = message['AutoScalingGroupName']
    instance_id = message['EC2InstanceId']

    ignore_instance = None
    if message['LifecycleTransition'] == 'autoscaling:EC2_INSTANCE_TERMINATING':
      ignore_instance = instance_id
      logger.info("The following instance-id should be ignored %s", instance_id)

    if (HOSTNAME_TAG_NAME_PUBLIC != ""):
      hostname_pattern, zone_id = fetch_tag_metadata(asg_name, HOSTNAME_TAG_NAME_PUBLIC)
      hostname = build_hostname(hostname_pattern, "")
      ip_addrs = process_asg(asg_name, hostname, ignore_instance, True)
      update_record(zone_id, ip_addrs, hostname)
    if (HOSTNAME_TAG_NAME_PRIVATE != ""):
      hostname_pattern, zone_id = fetch_tag_metadata(asg_name, HOSTNAME_TAG_NAME_PRIVATE)
      hostname = build_hostname(hostname_pattern, "")
      ip_addrs = process_asg(asg_name, hostname, ignore_instance, False)
      update_record(zone_id, ip_addrs, hostname)

# Picks out the message from a SNS message and deserializes it
def process_record(record):
    process_message(json.loads(record['Sns']['Message']))

# Main handler where the SNS events end up to
# Events are bulked up, so process each Record individually
def lambda_handler(event, context):
    logger.info("Processing SNS event: " + json.dumps(event))

    for record in event['Records']:
        process_record(record)

        # Finish the asg lifecycle operation by sending a continue result
        logger.info("Finishing ASG action")
        message = json.loads(record['Sns']['Message'])
        if LIFECYCLE_KEY in message and ASG_KEY in message :
            response = autoscaling.complete_lifecycle_action (
                LifecycleHookName     = message['LifecycleHookName'],
                AutoScalingGroupName  = message['AutoScalingGroupName'],
                InstanceId            = message['EC2InstanceId'],
                LifecycleActionToken  = message['LifecycleActionToken'],
                LifecycleActionResult = 'CONTINUE'
            )
            logger.info("ASG action complete: %s", response)
        else :
            logger.error("No valid JSON message")

# if invoked manually, assume someone pipes in a event json
if __name__ == "__main__":
    logging.basicConfig()

    lambda_handler(json.load(sys.stdin), None)


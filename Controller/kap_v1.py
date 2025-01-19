import os
import subprocess
import paramiko
from paramiko import AutoAddPolicy
from scp import SCPClient
from boto3 import client
import json
import time
import argparse
from pathlib import Path

#Obtain working directory
working_dir = os.getcwd().replace("\\","/")

#Obtain default arguments
with open(working_dir + "/config.json", "r") as file:
    scriptargs = json.load(file)

with open(scriptargs['tf_dir'] + "/Infra_deploy/dev.json", "r") as file:
    tfargs = json.load(file)

with open(working_dir + "/k8s_dinamic_vars.json", "r") as file:
     k8sargs = json.load(file)

#Set global variables
ssh_username = 'ubuntu'
ec2_name = 'kservice'

#Function to obtain data from an EC2 instance
def get_ec2_info(ec2_name, aws_region):
    ec2_client = client('ec2', region_name=aws_region)

    ec2_instance = ec2_client.describe_instances(
        Filters=[
            {'Name': 'instance-state-name', 'Values': ['running']},
            {'Name': 'tag:Name', 'Values': [ec2_name]}
        ]
    )

    if len(ec2_instance) == 0:
         raise Exception("Something went wrong. No resources where found.")

    return ec2_instance['Reservations'][0]['Instances'][0]

#Function to establish an SSH connection with a host
def ssh_connect(dns_name, username, private_key_path):
    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(AutoAddPolicy())
    ssh.connect(dns_name, username=username, key_filename=private_key_path)

    return ssh

#Function to execute a CLI command on a host through SSH
def ssh_exec(ssh_obj, cmd):
    stdin, stdout, stderr = ssh_obj.exec_command(cmd)

    return({'stdin':stdin, 'stdout':stdout, 'stderr':stderr})

#Function to perform a serial read of the output of a command
def serial_read(std):
    for line in std['stdout']:
        print(line.strip())
     
    for line in std['stderr']:
        print(line.strip())
     
#Function to copy a local file into a host directory through SCP
def scp_put_file(ssh_obj, src_path, dest_path):

    with SCPClient(ssh_obj.get_transport()) as scp:
        scp.put(src_path, dest_path)

#Function to restrieve a remote file from a host to a local directory
def scp_get_file(ssh_obj, src_path, dest_path):

    with SCPClient(ssh_obj.get_transport()) as scp:
        scp.get(src_path, dest_path)

#Function to tun a terraform command
def run_terraform_cmd(act, tf_dir, *args):

     cmd = ['terraform', f"-chdir={tf_dir}", act]

     if act not in ('init', 'plan', 'apply', 'destroy'):
          raise ValueError("Invalid argument.")
     
     if len(args) != 0:
          cmd = cmd + list(args)

     process = subprocess.Popen(
     cmd,
     stdout=subprocess.PIPE,
     stdin=subprocess.PIPE,
     stderr=subprocess.PIPE,
     text=True,
     encoding='utf-8'
     ) 

     return({'stdin':process.stdin, 'stdout':process.stdout, 'stderr':process.stderr})

#Function to modify JSON files
def mod_json(file_path, args):
     if not (os.path.exists(file_path)):
        data = args

     else:
          with open(file_path, 'r') as file:
               data = json.load(file)
    
          data.update(args)


     with open(file_path, 'w') as file:
                json.dump(data, file)  

#Function to add the specified arguments to their respective variables files
def add_args(argsdict):

     for key in argsdict.keys():
          
          if key in scriptargs.keys():
               scriptargs[key] = argsdict[key]

          if key in tfargs.keys():
               tfargs[key] = argsdict[key]

          if key in k8sargs.keys():
               k8sargs[key] = argsdict[key]

#Function to generate a dynamic Ansible inventory
def generate_inventory():
     
     inventory = {
          "all":{
               "vars":{
                    "ansible_user": "ubuntu",
                    "ansible_ssh_private_key_file": f"/home/ubuntu/{Path(scriptargs['private_key_path']).name}",
                    "ansible_ssh_extra_args": "-o StrictHostKeyChecking=no"
                },
                "hosts":{
                     "control":{
                        "ansible_host": "localhost"
                    }
                },
                "children":{
                    "k8snodes":{
                        "children":{
                            "mnodes":{},
                            "wknodes":{}
                        }
                    },
                    "mnodes":{
                        "children":{
                            "admin":{},
                            "managed":{}
                        }
                    },
                    "admin":{
                         "hosts":{} 
                    }, 
                    "managed":{
                         "hosts":{}
                    },
                    "wknodes":{
                         "hosts":{}
                    }
                }
            }
     }
     
     process = subprocess.run(['terraform',  f'-chdir={scriptargs["tf_dir"] + "/Infra_deploy"}', 'output', '-json'], stdout=subprocess.PIPE) 
     tf_output = json.loads(process.stdout)


     key = list(tf_output['kmasters_info']['value'].keys())[0]
     value = tf_output['kmasters_info']['value'][key]

     inventory['all']['children']['admin']['hosts'][key] = {"ansible_host": value}
     

     for key in list(tf_output['kmasters_info']['value'].keys())[1::]:
          value = tf_output['kmasters_info']['value'][key]
          inventory['all']['children']['managed']['hosts'][key] = {"ansible_host": value}

     for key in list(tf_output['kworkers_info']['value'].keys()):
          value = tf_output['kworkers_info']['value'][key]
          inventory['all']['children']['wknodes']['hosts'][key] = {"ansible_host": value}

     with open(working_dir + "/inventory.json", 'w') as file:
          json.dump(inventory, file, indent=4)

#Function to execute the Ansible component
def k8s_deploy():

     #Retrievement of the Service Node infromation
     count = 0
     while True:
          try:
               ec2 = get_ec2_info(ec2_name, tfargs["region"])
               break

          except Exception:
               count += 1
               time.sleep(5)
               if count == 6:
                    raise Exception("Error: Unable to reach kservice. Time exceeded.")
     
     #SSH connection establishment with the Service Node
     count = 0
     while True:
          try:
               ssh = ssh_connect(ec2['PublicDnsName'], ssh_username, scriptargs["private_key_path"])  
               print(f"Successful SSH connection with host {ec2['PublicDnsName']}")
               break
          
          except (paramiko.AuthenticationException, paramiko.SSHException, Exception) as e:
               print(f"Stablishing SSH connection with host {ec2['PublicDnsName']}...")
               count += 1
               time.sleep(5)
               if count == 24:
                    raise Exception(f"Error: Unable to stablish SHH connection. {e}")
               
     #Cluster configuration
     print("Configuring Cluster...")

     #Verification of the existance of the KAP directory in the Service Node
     count = 0
     while True:
          try:
               if ssh_exec(ssh, "touch /home/ubuntu/kap/")['stdout'].channel.recv_exit_status() != 0:
                    raise Exception("KAP directory not found.")
               print("KAP directory found")
               break
          
          except Exception as e:
               print("Configuring cluster environment...")
               count += 1
               time.sleep(5)
               if count == 60:
                    raise Exception(f"Error: Unable to configure cluster: {e}")

     #Modification of the Ansible's variables files with the new Service Node public IP
     mod_json(f"{working_dir}/k8s_dinamic_vars.json", {"lb_address_pub": ec2['PublicDnsName']})

     #Generation of the new inventory file
     generate_inventory()

     #Transmition of the dynamic files to the Service Node
     while True:
          try:
               scp_put_file(ssh, f"{working_dir}/k8s_dinamic_vars.json", "/home/ubuntu/kap/")
               scp_put_file(ssh, f"{working_dir}/inventory.json", "/home/ubuntu/kap/")
               break
          
          except Exception as e:
               print("Configuring cluster environment...")
               count += 1
               time.sleep(5)
               if count == 6:
                    raise Exception(f"Error: Unable to configure cluster: {e}")

     #Transmition of the SSH private key to the Service Node
     if (ssh_exec(ssh, f"stat /home/ubuntu/{Path(scriptargs['private_key_path']).name}")['stdout'].channel.recv_exit_status() != 0):
          print("Copying SSH key to Service Machine...")
          scp_put_file(ssh, scriptargs["private_key_path"], '/home/ubuntu/')
          ssh_exec(ssh, 'chmod 400 /home/ubuntu/test01-key.pem')          
     
     print("The cluster environment has been successfully configured.")

     #Execution of the Ansible component / playbook
     print("Deploying Cluster...")
     serial_read(ssh_exec(ssh, 'cd /home/ubuntu/kap/ && ansible-playbook k8s_deploy.yaml'))

     #Retrievement of the kubeconfig file from the Service Node
     print("Setting local environment...")
     scp_get_file(ssh, "/tmp/kap/kubeconfig", f"{scriptargs["kube_dir"]}/config")

     ssh.close()

     print("The cluster has been succesfully deployed.\n\nTry to execute 'kubectl get nodes' from your working directory.\n\n")
     print("Execute 'kubectl port-forward -n kubernetes-dashboard service/kubernetes-dashboard-kong-proxy 8443:443' to expose the Kubernetes dashboard.")
     print("You can access it by seraching 'https://localhost:8443' on your borwser.\n\n")
     print("Execute kubectl -n kubernetes-dashboard create token admin-user to generate a token to access the Dasboard.\n\n")
    

#Function to execute the Terraform component
def create_cluster():
          
     #Initiation of the Terraform working directory is not initiated yet
     if not (os.path.isdir(scriptargs["tf_dir"] + '/Infra_deploy/.terraform')):
          print("Initializing Terraform environment...")
          run_terraform_cmd('init', scriptargs["tf_dir"] + '/Infra_deploy') 

     a = input("Would you like to check the changes that will be applied to your AWS account before applying? (yes/no)\nOnly 'yes' will be accepted to approve.\n\nEnter value: ")

     if a not in ('yes', 'no'):
          raise ValueError("Invalid argument. Only yes/no is valid.")
     
     if a == 'yes':

          #Execution of Terraform plan
          print("Printing changes...")
          serial_read(run_terraform_cmd('plan', scriptargs["tf_dir"] + "/Infra_deploy", f'-out={scriptargs["tf_dir"] + "/Infra_deploy/k8s-plan.tfplan"}', f"-var-file={scriptargs["tf_dir"] + "/Infra_deploy/dev.json"}"))

          b = input("\nWould you like to apply this changes? (yes/no)\nOnly 'yes' will be accepted to approve.\n\nEnter value: ")

          if b not in ('yes', 'no'):
               raise ValueError("Invalid argument. Only yes/no is valid.")
     
          if b == 'yes':

               #Execution of Terraform apply
               print("Applying changes...")
               serial_read(run_terraform_cmd('apply', scriptargs["tf_dir"] + "/Infra_deploy", scriptargs["tf_dir"] + "/Infra_deploy/k8s-plan.tfplan"))
               k8s_deploy()

          elif b == 'no':
               print("Apply cancelled.\nPlease contact with the application manager for more information.\n")
               print(f"If you know what you are doing, change the terraform's main file in {scriptargs["tf_dir"]}/Infra_deploy directory according to your needs.\nWe don't garantee the correct functionality of the application if changes are made.")

     elif a == 'no':

          #Execution of Terraform plan and apply if no validation has been requeted
          print("Applying changes...")
          serial_read(run_terraform_cmd('plan', scriptargs["tf_dir"] + "/Infra_deploy", f'-out={scriptargs["tf_dir"] + "/Infra_deploy/k8s-plan.tfplan"}', f"-var-file={scriptargs["tf_dir"] + "/Infra_deploy/dev.json"}"))
          serial_read(run_terraform_cmd('apply', scriptargs["tf_dir"] + "/Infra_deploy", scriptargs["tf_dir"] + "/Infra_deploy/k8s-plan.tfplan"))
          k8s_deploy()

#Function to destroy the cluster
def destroy_cluster():
     a = input("Do you want to destroy the cluster? (yes/no)\n¡Remember to save your changes on an external datastore if needed!\nOnly 'yes' will be accepted to approve.\n\nEnter value: ")

     if a not in ('yes', 'no'):
          raise ValueError("Invalid argument. Only yes/no is valid.")
     
     if a == 'yes':

          #Execution of Terraform destroy
          print("Destroying cluster...")
          serial_read(run_terraform_cmd('destroy', scriptargs["tf_dir"] + "/Infra_deploy", f"-var-file={scriptargs["tf_dir"] + "/Infra_deploy/dev.json"}", "-auto-approve"))
          if os.path.exists(scriptargs['kube_dir'] + "/config"):
               print("Removing Kubernetes configuration...\n")
               os.remove(scriptargs['kube_dir'] + "/config")
          print("Cluster was destroyed with exit!!!")
     
     elif a == 'no':
          print("Destruction cancelled.")

#Function to access an existing cluster
def join_cluster():

     #Retrievement of the Service Node infromation
     count = 0
     while True:
          try:
               ec2 = get_ec2_info(ec2_name, tfargs["region"])
               break

          except Exception:
               count += 1
               time.sleep(5)
               if count == 6:
                    raise Exception("Error: Unable to reach kservice. Time exceeded.")

     #SSH connection establishment with the Service Node
     count = 0         
     while True:
          try:
               ssh = ssh_connect(ec2['PublicDnsName'], ssh_username, scriptargs["private_key_path"])  
               print(f"Successful SSH connection with host {ec2['PublicDnsName']}")
               break
          
          except (paramiko.AuthenticationException, paramiko.SSHException, Exception) as e:
               print(f"Stablishing SSH connection with host {ec2['PublicDnsName']}...")
               count += 1
               time.sleep(5)
               if count == 24:
                    raise Exception(f"Error: Unable to stablish SHH connection. {e}")

      #Retrievement of the kubeconfig file from the Service Node
     print("Setting local environment...")
     scp_get_file(ssh, "/home/ubuntu/.kube/config", scriptargs["kube_dir"])
               
#Function to validate the format of the -n option
def validate_format(valor):
    try:
        masters, workers = valor.split(":")
        return {'num_masters':int(masters), 'num_workers':int(workers)}
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{valor}' no tiene el formato int:int (ejemplo: 5:10)")
    
#Function to verify that de-scaling has not been requested
def validate_scaling():
    try:  
        get_ec2_info(ec2_name, args["region"])
       
    except Exception:
         return
    
    print("A cluster was found. Applying modifications...")
    if args["num_masters"] < tfargs["num_masters"] or args["num_workers"] < tfargs["num_workers"]:
          raise Exception("De-scalation is not supported. To de-scale, destroy and redeploy the cluster with the desired dimentions.")

#Arguments declaration
parse = argparse.ArgumentParser()
parse.add_argument("mode", choices=['create','destroy', 'join-cluster', 'reset-args', 'list-args', 'save'])
parse.add_argument("-n", default=f"{tfargs["num_masters"]}:{tfargs["num_workers"]}", type=validate_format)
parse.add_argument("-kubernetes-version", default=k8sargs["kubernetes_version"])
parse.add_argument("-tf-dir", default=scriptargs["tf_dir"])
parse.add_argument("-kube-dir", default=scriptargs["kube_dir"])
parse.add_argument("-private-key-path", default=scriptargs["private_key_path"])
parse.add_argument("-s3-credentials-path", default=scriptargs["s3_credentials_path"])
parse.add_argument("-backup-namespaces", default="default")
parse.add_argument("-region", default=tfargs["region"])
parse.add_argument("-instance-type", default=None)
parse.add_argument("-master-instance-type", default=tfargs["master_instance_type"])
parse.add_argument("-worker-instance-type", default=tfargs["worker_instance_type"])
parse.add_argument("-service-instance-type", default=tfargs["service_instance_type"])

#Arguments processing
args = vars(parse.parse_args())

args["key_name"] = Path(args['private_key_path']).stem

if args['instance_type'] != None: 
     for key in ('master_instance_type', 'worker_instance_type', 'service_instance_type'):
        args[key] = args['instance_type']

args.update(args['n'])
validate_scaling()
backup_setting()

add_args(args)

mod_json(scriptargs["tf_dir"] + "/Infra_deploy/dev.json", tfargs)
mod_json(scriptargs["tf_dir"] + "/s3_deploy/dev.json", {"region":tfargs["region"]})
mod_json(working_dir + "/config.json", scriptargs)
mod_json(working_dir + "/k8s_dinamic_vars.json", k8sargs)

#Subcommands processing
if args['mode'] == "create":
     create_cluster()

elif args['mode'] == "destroy":
     destroy_cluster()

elif args['mode'] == "reset-args":
     scriptargs = {
          "kube_dir": "", 
          "tf_dir": "", 
          "private_key_path": "", 
          "s3_credentials_path": "", 
          "backup_namespaces": "default"
     }
     tfargs = {
          "region": "eu-west-3", 
          "key_name": "", 
          "master_instance_type": "t4g.small", 
          "worker_instance_type": "t4g.small", 
          "service_instance_type": "t4g.small", 
          "num_masters": 3, 
          "num_workers": 2
     }
     k8sargs = {"lb_address_pub": "",
          "kubernetes_version": "1.31", 
          "region": "eu-west-3", 
          "backup": False, 
          "backup_name": "test01"
     }
     

     mod_json(scriptargs["tf_dir"] + "/Infra_deploy/dev.json", tfargs)
     mod_json(working_dir + "/config.json", scriptargs)

     print("Arguments reseted successfully!!")

elif args['mode'] == "list-args":
     print("Current configuration is:\n")

     print("Environmental configuration:")
     for key in scriptargs:
          print(f"{key}: {scriptargs[key]}")
     
     print("\n")

     print("Terraform configuration:")
     for key in tfargs:
          print(f"{key}: {tfargs[key]}")

     print("\n")

     print("Cluster configuration:")
     for key in k8sargs:
          print(f"{key}: {k8sargs[key]}")

     print("\n")

elif args['mode'] == "join-cluster":
     join_cluster()

elif args['mode'] == 'save':
     save_cluster()

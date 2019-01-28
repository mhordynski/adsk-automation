#!/usr/bin/env python3

import argparse
import shutil
import subprocess

import boto3
from git import Repo


class Main:
    CAR_RENTAL_TAG_NAME = 'CarRentalServerPurpose'

    def __init__(self):
        self.args = self.parse_arguments()

        self.loadbalancer_servers = []
        self.metric_servers = []
        self.app_servers = []

        self.ec2 = boto3.client('ec2', region_name=self.args.aws_region)

    def __call__(self, *args, **kwargs):
        print(f"[***] Cloning repository from {self.args.repo_url}")
        self.get_repo()

        if not self.args.skip_build:
            print("[***] Packaging with maven")
            self.maven_package()

        print("[***] ec2 setup")
        self.configure_ec2()

        print("[***] generating hosts.ini file")
        self.generate_hosts_file()

        print("[***] running ansible playbook")
        self.run_ansible()
        self.show_results()

    @staticmethod
    def parse_arguments():
        parser = argparse.ArgumentParser('Deploys car rental app to aws')
        parser.add_argument('--app_instances', help='How many instances of application should be created',
                            type=int, default=2)
        parser.add_argument('--repo_url', help='URL to repo with application to be deployed',
                            type=str, default='https://github.com/jkanclerz/car-rental-spring.git')
        parser.add_argument('--skip_tests', help='Pass this flag to skip tests before deployment',
                            type=bool, default=False)
        parser.add_argument('--skip_build', help='Pass this flag to skip build before deployment',
                            type=bool, default=False)
        parser.add_argument('--aws_region', help='Name of AWS region',
                            type=str, default='eu-west-1')
        return parser.parse_args()

    def get_repo(self):
        try:
            shutil.rmtree('./src/')
        except FileNotFoundError:
            pass

        Repo.clone_from(self.args.repo_url, './src/')

    @staticmethod
    def extract_ip(instances):
        rv = map(lambda x: x['PublicIpAddress'], instances[0]['Instances'])
        return list(rv)

    def configure_ec2(self):

        metric_filter = {
            'Name': f'tag:{self.CAR_RENTAL_TAG_NAME}',
            'Values': ['metrics']
        }

        loadbalancer_filter = {
            'Name': f'tag:{self.CAR_RENTAL_TAG_NAME}',
            'Values': ['loadbalancer']
        }

        app_filter = {
            'Name': f'tag:{self.CAR_RENTAL_TAG_NAME}',
            'Values': ['application']
        }

        running_filter = {
            'Name': 'instance-state-name',
            'Values': ['running']
        }

        app_instances = self.ec2.describe_instances(Filters=[running_filter, app_filter])['Reservations']
        metric_instances = self.ec2.describe_instances(Filters=[running_filter, metric_filter])['Reservations']
        loadbalancer_instances = self.ec2.describe_instances(Filters=[running_filter, loadbalancer_filter])[
            'Reservations']

        self.app_servers = self.extract_ip(app_instances)
        self.metric_servers = self.extract_ip(metric_instances)
        self.loadbalancer_servers = self.extract_ip(loadbalancer_instances)

    def maven_package(self):
        command = ['mvn', 'package', '-f', 'src/']

        if self.args.skip_tests:
            command.append('-DskipTests')

        subprocess.run(command)

    @staticmethod
    def generate_server_lines(ip_list):
        return map(lambda x: f'{x} ansible_user=ec2-user', ip_list)

    def generate_hosts_file(self):

        lines = ['[application]']
        lines += self.generate_server_lines(self.app_servers)
        lines.append('[application:vars]')
        lines.append(f'metrics_server={self.metric_servers[0]}')
        lines.append('[metrics]')
        lines += self.generate_server_lines(self.metric_servers)
        lines.append('[loadbalancer]')
        lines += self.generate_server_lines(self.loadbalancer_servers)
        lines.append('[loadbalancer:vars]')
        lines.append(f'apps={self.app_servers}')

        lines = map(lambda x: x + '\n', lines)

        with open('hosts.ini', 'w') as f:
            f.writelines(lines)

    @staticmethod
    def run_ansible():
        subprocess.run(['ansible-playbook', 'setup.yml', '-i', 'hosts.ini'])

    def show_results(self):
        print('[***] All done: ')
        print(f'Application endpoint: http://{self.loadbalancer_servers[0]}')
        print(f'Metrics endpoint: http://{self.metric_servers[0]}')


if __name__ == '__main__':
    main = Main()
    main()

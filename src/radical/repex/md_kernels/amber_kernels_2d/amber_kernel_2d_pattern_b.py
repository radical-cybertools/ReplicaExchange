"""
.. module:: radical.repex.md_kernles.amber_kernels_salt.amber_kernel_salt_pattern_b
.. moduleauthor::  <haoyuan.chen@rutgers.edu>
.. moduleauthor::  <antons.treikalis@rutgers.edu>
"""

__copyright__ = "Copyright 2013-2014, http://radical.rutgers.edu"
__license__ = "MIT"

import os
import sys
import time
import math
import json
import random
import shutil
import datetime
from os import path
import radical.pilot
from kernels.kernels import KERNELS
from replicas.replica import Replica2d
from md_kernels.md_kernel_2d import *
import amber_kernels_salt.amber_matrix_calculator_pattern_b
import amber_kernels_tex.amber_matrix_calculator_pattern_b
import amber_kernels_2d.amber_matrix_calculator_2d_pattern_b

#-----------------------------------------------------------------------------------------------------------------------------------

class AmberKernel2dPatternB(MdKernel2d):
    """This class is responsible for performing all operations related to Amber for RE scheme S2.
    In this class is determined how replica input files are composed, how exchanges are performed, etc.

    RE pattern B:
    - Synchronous RE scheme: none of the replicas can start exchange before all replicas has finished MD run.
    Conversely, none of the replicas can start MD run before all replicas has finished exchange step. 
    In other words global barrier is present.   
    - Number of replicas is greater than number of allocated resources for both MD and exchange step.
    - Simulation cycle is defined by the fixed number of simulation time-steps for each replica.
    - Exchange probabilities are determined using Gibbs sampling.
    - Exchange step is performed in decentralized fashion on target resource.

    """
    def __init__(self, inp_file,  work_dir_local):
        """Constructor.

        Arguments:
        inp_file - package input file with Pilot and NAMD related parameters as specified by user 
        work_dir_local - directory from which main simulation script was invoked
        """

        MdKernel2d.__init__(self, inp_file, work_dir_local)

        self.pre_exec = KERNELS[self.resource]["kernels"]["amber"]["pre_execution"]
        try:
            self.amber_path = inp_file['input.MD']['amber_path']
        except:
            print "Using default Amber path for %s" % inp_file['input.PILOT']['resource']
            try:
                self.amber_path = KERNELS[self.resource]["kernels"]["amber"]["executable"]
            except:
                print "Amber path for localhost is not defined..."

        self.amber_restraints = inp_file['input.MD']['amber_restraints']
        self.amber_coordinates = inp_file['input.MD']['amber_coordinates']
        self.amber_parameters = inp_file['input.MD']['amber_parameters']
        self.amber_input = inp_file['input.MD']['amber_input']
        self.input_folder = inp_file['input.MD']['input_folder']

        self.d1_id_matrix = []
        self.d2_id_matrix = []
        self.temp_matrix = []
        self.salt_matrix = []

        self.current_cycle = -1

#-----------------------------------------------------------------------------------------------------------------------------------

    def build_input_file(self, replica, shared_data_url):
        """Builds input file for replica, based on template input file ala10.mdin
        """
        basename = self.inp_basename

        new_input_file = "%s_%d_%d.mdin" % (basename, replica.id, replica.cycle)
        outputname = "%s_%d_%d.mdout" % (basename, replica.id, replica.cycle)
        old_name = "%s_%d_%d" % (basename, replica.id, (replica.cycle-1))

        # new files
        replica.new_coor = "%s_%d_%d.rst" % (basename, replica.id, replica.cycle)
        replica.new_traj = "%s_%d_%d.mdcrd" % (basename, replica.id, replica.cycle)
        replica.new_info = "%s_%d_%d.mdinfo" % (basename, replica.id, replica.cycle)

        # old files
        replica.old_coor = old_name + ".rst"
        replica.old_traj = old_name + ".mdcrd"
        replica.old_info = old_name + ".mdinfo"

        restraints = self.amber_restraints

        try:
            r_file = open( (os.path.join((self.work_dir_local + "/" + self.input_folder + "/"), self.amber_input)), "r")
        except IOError:
            print 'Warning: unable to access template file %s' % self.amber_input

        tbuffer = r_file.read()
        r_file.close()
      
        tbuffer = tbuffer.replace("@nstlim@",str(self.cycle_steps))
        tbuffer = tbuffer.replace("@temp@",str(int(replica.new_temperature)))
        tbuffer = tbuffer.replace("@salt@",str(float(replica.new_salt_concentration)))
        tbuffer = tbuffer.replace("@rstr@", restraints )
        
        replica.cycle += 1

        try:
            w_file = open(new_input_file, "w")
            w_file.write(tbuffer)
            w_file.close()
        except IOError:
            print 'Warning: unable to access file %s' % new_input_file
     
#-----------------------------------------------------------------------------------------------------------------------------------
    
    def prepare_shared_md_input(self):
        """Creates a Compute Unit for shared data staging in
        these are Amber input files shared between all replicas
        """

        shared_data_unit = radical.pilot.ComputeUnitDescription()

        crds = self.work_dir_local + "/" + self.inp_folder + "/" + self.amber_coordinates
        parm = self.work_dir_local + "/" + self.inp_folder + "/" + self.amber_parameters
        rstr = self.work_dir_local + "/" + self.inp_folder + "/" + self.amber_restraints

        shared_data_unit.executable = "/bin/true"
        shared_data_unit.cores = 1
        shared_data_unit.input_staging = [str(crds), str(parm)]
 
        return shared_data_unit

#-----------------------------------------------------------------------------------------------------------------------------------
    def prepare_replicas_for_md(self, replicas, shared_data_url):
        """
        """

        compute_replicas = []
        for r in range(len(replicas)):
            # need to avoid this step!
            self.build_input_file(replicas[r], shared_data_url)
      
            # in principle restraint file should be moved to shared directory
            rstr = self.work_dir_local + "/" + self.inp_folder + "/" + self.amber_restraints
            input_file = "%s_%d_%d.mdin" % (self.inp_basename, replicas[r].id, (replicas[r].cycle-1))
            # this is not transferred back
            output_file = "%s_%d_%d.mdout" % (self.inp_basename, replicas[r].id, (replicas[r].cycle-1))

            new_coor = replicas[r].new_coor
            new_traj = replicas[r].new_traj
            new_info = replicas[r].new_info
            old_coor = replicas[r].old_coor
            old_traj = replicas[r].old_traj

            if replicas[r].cycle == 1:
                cu = radical.pilot.ComputeUnitDescription()
                cu.executable = self.amber_path
                cu.pre_exec = self.pre_exec
                cu.mpi = self.replica_mpi
                cu.arguments = ["-O", "-i ", input_file, 
                                      "-o ", output_file, 
                                      "-p ", shared_data_url + "/" + self.amber_parameters, 
                                      "-c ", shared_data_url + "/" + self.amber_coordinates, 
                                      "-r ", new_coor, 
                                      "-x ", new_traj, 
                                      "-inf ", new_info]

                cu.cores = self.replica_cores
                cu.input_staging = [str(input_file), str(rstr)]
                cu.output_staging = [str(new_coor)]
                compute_replicas.append(cu)
            else:
                cu = radical.pilot.ComputeUnitDescription()
                cu.executable = self.amber_path
                cu.pre_exec = self.pre_exec
                cu.mpi = self.replica_mpi
                cu.arguments = ["-O", "-i ", input_file, 
                                      "-o ", output_file, 
                                      "-p ", shared_data_url + "/" + self.amber_parameters, 
                                      "-c ", shared_data_url + "/" + self.amber_coordinates, 
                                      "-r ", new_coor, 
                                      "-x ", new_traj, 
                                      "-inf ", new_info]

                cu.cores = self.replica_cores
                cu.input_staging = [str(input_file), str(rstr)]
                cu.output_staging = [str(new_coor)]
                compute_replicas.append(cu)

        return compute_replicas

#-----------------------------------------------------------------------------------------------------------------------------------
    def prepare_replicas_for_exchange(self, dimension, replicas, shared_data_url):
        """
        """
        for r in range(len(replicas)):
            # name of the file which contains swap matrix column data for each replica
            matrix_col = "matrix_column_%s_%s.dat" % (r, (replicas[r].cycle-1))
            basename = self.inp_basename
            exchange_replicas = []

            if dimension == 1:
                for r in range(len(replicas)):
                    cu = radical.pilot.ComputeUnitDescription()
                    cu.executable = "python"
                    # path!
                    calculator_path = os.path.dirname(amber_kernels_tex.amber_matrix_calculator_pattern_b.__file__)
                    calculator = calculator_path + "/amber_matrix_calculator_pattern_b.py" 
                    #calculator_path = os.path.dirname(amber_kernels_2d.amber_matrix_calculator_2d_pattern_b.__file__)
                    #calculator = calculator_path + "/amber_matrix_calculator_2d_pattern_b.py"
                    cu.input_staging = [str(calculator)]
                    cu.arguments = ["amber_matrix_calculator_pattern_b.py", r, (replicas[r].cycle-1), len(replicas), basename]
                    cu.cores = 1            
                    exchange_replicas.append(cu)
         
            else:
                all_salt = ""
                for r in range(len(replicas)):
                    if r == 0:
                        all_salt = str(replicas[r].new_salt_concentration)
                    else:
                        all_salt = all_salt + " " + str(replicas[r].new_salt_concentration)

                all_salt_list = all_salt.split(" ")

                all_temp = ""
                for r in range(len(replicas)):
                    if r == 0:
                        all_temp = str(replicas[r].new_temperature)
                    else:
                        all_temp = all_temp + " " + str(replicas[r].new_temperature)

                all_temp_list = all_temp.split(" ")


                for r in range(len(replicas)):
                    cu = radical.pilot.ComputeUnitDescription()
                    cu.pre_exec = ["module load amber/14"]
                    cu.executable = "python"
                    # path!
                    #calculator_path = os.path.dirname(amber_kernels_salt.amber_matrix_calculator_pattern_b.__file__)
                    #calculator = calculator_path + "/amber_matrix_calculator_pattern_b.py" 
                    calculator_path = os.path.dirname(amber_kernels_2d.amber_matrix_calculator_2d_pattern_b.__file__)
                    calculator = calculator_path + "/amber_matrix_calculator_2d_pattern_b.py"
                    input_file = self.work_dir_local + "/" + self.input_folder + "/" + self.amber_input

                    data = {
                        "replica_id": str(r),
                        "replica_cycle" : str(replicas[r].cycle-1),
                        "replicas" : str(len(replicas)),
                        "base_name" : str(basename),
                        "init_temp" : str(replicas[r].new_temperature),
                        #"init_temp" : str(self.init_temperature),
                        "amber_path" : str(self.amber_path),
                        "shared_path" : str(shared_data_url),
                        "amber_input" : str(self.amber_input),
                        "amber_parameters": str(self.amber_parameters),
                        "all_salt_ctr" : all_salt, 
                        "all_temp" : all_temp
                    }

                    dump_data = json.dumps(data)
                    json_data = dump_data.replace("\\", "")
                    # in principle we can transfer this just once and use it multiple times later during the simulation
                    cu.input_staging = [str(calculator), str(input_file), str(replicas[r].new_coor)]
                    cu.arguments = ["amber_matrix_calculator_2d_pattern_b.py", json_data]
                    cu.cores = 1            
                    exchange_replicas.append(cu)

        return exchange_replicas


#-----------------------------------------------------------------------------------------------------------------------------------

    def exchange_params(self, dimension, replica_1, replica_2):
        if dimension == 1:
            temp = replica_2.new_temperature
            replica_2.new_temperature = replica_1.new_temperature
            replica_1.new_temperature = temp
        else:
            salt = replica_2.new_salt_concentration
            replica_2.new_salt_concentration = replica_1.new_salt_concentration
            replica_1.new_salt_concentration = salt

#-----------------------------------------------------------------------------------------------------------------------------------

    def do_exchange(self, dimension, replicas, swap_matrix):
        print "dimension: %d" % dimension
        print "replica id's in current group: "
        for r_i in replicas:
            print r_i.id

        for r_i in replicas:
            r_j = self.gibbs_exchange(r_i, replicas, swap_matrix)
            if (r_j != r_i):
                # swap parameters
                self.exchange_params(dimension, r_i, r_j)               
                # record that swap was performed
                r_i.swap = 1
                r_j.swap = 1
                # update id matrix
                if dimension == 1:
                    self.d1_id_matrix[r_i.id][self.current_cycle] = r_j.id
                    self.d1_id_matrix[r_j.id][self.current_cycle] = r_i.id
                else:
                    self.d2_id_matrix[r_i.id][self.current_cycle] = r_j.id
                    self.d2_id_matrix[r_j.id][self.current_cycle] = r_i.id

        for replica in replicas:
            if dimension == 1:
                # update temp_matrix
                self.temp_matrix[replica.id][self.current_cycle + 1] = replica.new_temperature
            else:
                # update salt_matrix
                self.salt_matrix[replica.id][self.current_cycle + 1] = replica.new_salt_concentration

#-----------------------------------------------------------------------------------------------------------------------------------

    def select_for_exchange(self, dimension, replicas, swap_matrix, cycle):

        self.current_cycle = cycle

        salt_list = []
        temp_list = []
        for r1 in range(len(replicas)):
            ###############################################
            # temperature exchange
            if dimension == 1:
                current_salt = replicas[r1].new_salt_concentration
                if current_salt not in salt_list:
                    salt_list.append(current_salt)
                    current_group = []
                    #current_group.append(replicas[r1])
                    for r2 in replicas:
                        if current_salt == r2.new_salt_concentration:
                            current_group.append(r2)
                    #######################################
                    # remove
                    print "current dimension: %d" % dimension
                    print "current group: "
                    for rt in current_group:
                        print rt.new_salt_concentration
                        print rt.new_temperature
                    #######################################
                    # perform exchange among group members
                    #######################################
                    self.do_exchange(dimension, current_group, swap_matrix)
            ###############################################
            # salt concentration exchange
            else:
                current_temp = replicas[r1].new_temperature
                if current_temp not in temp_list:
                    temp_list.append(current_temp)
                    current_group = []
                    #current_group.append(replicas[r1])
                    for r2 in replicas:
                        if current_temp == r2.new_temperature:
                            current_group.append(r2)
                    #######################################
                    # remove
                    print "current dimension: %d" % dimension
                    print "current group: "
                    for rt in current_group:
                        print rt.new_salt_concentration
                        print rt.new_temperature
                    #######################################
                    # perform exchange among group members
                    #######################################
                    self.do_exchange(dimension, current_group, swap_matrix)


#-----------------------------------------------------------------------------------------------------------------------------------

    def init_matrices(self, replicas):

        # id_matrix
        for r in replicas:
            row = []
            row.append(r.id)
            for c in range(self.nr_cycles):
                row.append( -1.0 )

            self.d1_id_matrix.append( row )
            self.d2_id_matrix.append( row )

        self.d1_id_matrix = sorted(self.d1_id_matrix)
        self.d2_id_matrix = sorted(self.d2_id_matrix)
        print "d1_id_matrix is: "
        print self.d1_id_matrix

        print "d2_id_matrix is: "
        print self.d2_id_matrix

        # temp_matrix
        for r in replicas:
            row = []
            row.append(r.id)
            row.append(r.new_temperature)
            for c in range(self.nr_cycles - 1):
                row.append( -1.0 )

            self.temp_matrix.append( row )

        self.temp_matrix = sorted(self.temp_matrix)
        print "temp_matrix is: "
        print self.temp_matrix

        # salt_matrix
        for r in replicas:
            row = []
            row.append(r.id)
            row.append(r.new_salt_concentration)
            for c in range(self.nr_cycles - 1):
                row.append( -1.0 )

            self.salt_matrix.append( row )

        self.salt_matrix = sorted(self.salt_matrix)
        print "salt_matrix is: "
        print self.salt_matrix


#-----------------------------------------------------------------------------------------------------------------------------------

    def get_d1_id_matrix(self):
        return self.d1_id_matrix

#-----------------------------------------------------------------------------------------------------------------------------------

    def get_d2_id_matrix(self):
        return self.d2_id_matrix

#-----------------------------------------------------------------------------------------------------------------------------------

    def get_temp_matrix(self):
        return self.temp_matrix

#-----------------------------------------------------------------------------------------------------------------------------------

    def get_salt_matrix(self):
        return self.salt_matrix
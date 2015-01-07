"""
.. module:: radical.repex.pilot_kernels.pilot_kernel_pattern_b
.. moduleauthor::  <antons.treikalis@rutgers.edu>
"""

__copyright__ = "Copyright 2013-2014, http://radical.rutgers.edu"
__license__ = "MIT"

import os
import sys
import time
import math
import json
import datetime
from os import path
import radical.pilot
from pilot_kernels.pilot_kernel import *

#-----------------------------------------------------------------------------------------------------------------------------------

class PilotKernelPatternB2d(PilotKernel):
    """This class is responsible for performing all Radical Pilot related operations for RE pattern B.
    This includes pilot launching, running main loop of RE simulation and using RP API for data staging in and out. 

    RE pattern B:
    - Synchronous RE scheme: none of the replicas can start exchange before all replicas has finished MD run.
    Conversely, none of the replicas can start MD run before all replicas has finished exchange step. 
    In other words global barrier is present.   
    - Number of replicas is greater than number of allocated resources for both MD and exchange step.
    - Simulation cycle is defined by the fixed number of simulation time-steps for each replica.
    - Exchange probabilities are determined using Gibbs sampling.
    - Exchange step is performed in decentralized fashion on target resource.
    """
    def __init__(self, inp_file):
        """Constructor.

        Arguments:
        inp_file - json input file with Pilot and NAMD related parameters as specified by user 
        """
        PilotKernel.__init__(self, inp_file)

#-----------------------------------------------------------------------------------------------------------------------------------
    def getkey(self, item):
        return item[0]


    def compose_swap_matrix(self, replicas, matrix_columns):
        """Creates a swap matrix from matrix_column_x.dat files. 
        matrix_column_x.dat - is populated on targer resource and then transferred back. This
        file is created for each replica and has data for one column of swap matrix. In addition to that,
        this file holds path to pilot compute unit of the previous run, where reside NAMD output files for 
        a given replica. 

        Arguments:
        replicas - list of Replica objects

        Returns:
        swap_matrix - 2D list of lists of dimension-less energies, where each column is a replica 
        and each row is a state
        """
 
        # init matrix
        swap_matrix = [[ 0. for j in range(len(replicas))] 
             for i in range(len(replicas))]

        matrix_columns = sorted(matrix_columns)
        print "matrix columns: "
        print matrix_columns

        for r in replicas:
            # populating one column at a time
            for i in range(len(replicas)):
                swap_matrix[i][r.id] = float(matrix_columns[r.id][i])

            # setting old_path and first_path for each replica
            if ( r.cycle == 1 ):
                r.first_path = matrix_columns[r.id][len(replicas)]
                r.old_path = matrix_columns[r.id][len(replicas)]
            else:
                r.old_path = matrix_columns[r.id][len(replicas)]

        return swap_matrix

#-----------------------------------------------------------------------------------------------------------------------------------

    def run_simulation(self, replicas, pilot_object, session,  md_kernel ):
        """This function runs the main loop of RE simulation for RE pattern B.

        Arguments:
        replicas - list of Replica objects
        pilot_object - radical.pilot.ComputePilot object
        session - radical.pilot.session object, the *root* object for all other RADICAL-Pilot objects 
        md_kernel - an instance of NamdKernelScheme2a class
        """
  
        unit_manager = radical.pilot.UnitManager(session, scheduler=radical.pilot.SCHED_ROUND_ROBIN)
        unit_manager.register_callback(unit_state_change_cb)
        unit_manager.add_pilots(pilot_object)

        # staging shared input data in
        shared_data_unit_descr = md_kernel.prepare_shared_md_input()
        staging_unit = unit_manager.submit_units(shared_data_unit_descr)
        unit_manager.wait_units()

        # get the path to the directory containing the shared data
        shared_data_url = radical.pilot.Url(staging_unit.working_directory).path

        print "###################################"
        print "replica params are: "
        for r in replicas:
            print r.new_salt_concentration
            print r.new_temperature

        print "###################################"

        md_kernel.init_matrices(replicas)

        for i in range(md_kernel.nr_cycles):

            current_cycle = i+1
            start_time = datetime.datetime.utcnow()
            print "Performing cycle: %s" % current_cycle
            #########
            # D1 run (temperature exchange)
            D = 1
            print "Preparing %d replicas for MD run (dimension 1; cycle %d)" % (md_kernel.replicas, current_cycle)
            compute_replicas = md_kernel.prepare_replicas_for_md(replicas, shared_data_url)
            print "Submitting %d replicas for MD run (dimension 1; cycle %d)" % (md_kernel.replicas, current_cycle)
            submitted_replicas = unit_manager.submit_units(compute_replicas)
            unit_manager.wait_units()
            
            stop_time = datetime.datetime.utcnow()
            print "Cycle %d; dimension 1; Time to perform MD run: %f" % (current_cycle, (stop_time - start_time).total_seconds())            

            # this is not done for the last cycle
            if (i != (md_kernel.nr_cycles-1)):
                start_time = datetime.datetime.utcnow()
                #########################################
                # computing swap matrix
                #########################################
                print "Preparing %d replicas for Exchange run (dimension 1; cycle %d)" % (md_kernel.replicas, current_cycle)
                #########################################
                # selecting replicas for exchange step
                #########################################

                exchange_replicas = md_kernel.prepare_replicas_for_exchange(D, replicas, shared_data_url)
                print "Submitting %d replicas for Exchange run (dimension 1; cycle %d)" % (md_kernel.replicas, current_cycle)
                submitted_replicas = unit_manager.submit_units(exchange_replicas)
                unit_manager.wait_units()
                stop_time = datetime.datetime.utcnow()
                print "Cycle %d; dimension 1; Time to perform Exchange: %f" % (current_cycle, (stop_time - start_time).total_seconds())
                start_time = datetime.datetime.utcnow()

                matrix_columns = []
                for r in submitted_replicas:
                    d = str(r.stdout)
                    data = d.split()
                    matrix_columns.append(data)

                ##############################################
                # compose swap matrix from individual files
                ##############################################
                print "Composing swap matrix from individual files for all replicas"
                swap_matrix = self.compose_swap_matrix(replicas, matrix_columns)
            
                print "Performing exchange"
                md_kernel.select_for_exchange(D, replicas, swap_matrix, current_cycle)

                stop_time = datetime.datetime.utcnow()
                print "Cycle %d; dimension 1; Post-processing time: %f" % (current_cycle, (stop_time - start_time).total_seconds())
 
            start_time = datetime.datetime.utcnow()
            #########################################
            # D2 run (salt concentration exchange)
            D = 2
            print "Preparing %d replicas for MD run (dimension 2; cycle %d)" % (md_kernel.replicas, current_cycle)
            compute_replicas = md_kernel.prepare_replicas_for_md(replicas, shared_data_url)
            print "Submitting %d replicas for MD run (dimension 2; cycle %d)" % (md_kernel.replicas, current_cycle)
            submitted_replicas = unit_manager.submit_units(compute_replicas)
            unit_manager.wait_units()

            stop_time = datetime.datetime.utcnow()
            print "Cycle %d; dimension 2; Time to perform MD run: %f" % (current_cycle, (stop_time - start_time).total_seconds())

            
            # this is not done for the last cycle
            if (i != (md_kernel.nr_cycles-1)):
                start_time = datetime.datetime.utcnow()
                ##########################
                # computing swap matrix
                ##########################
                print "Preparing %d replicas for Exchange run (dimension 2; cycle %d)" % (md_kernel.replicas, current_cycle)
                exchange_replicas = md_kernel.prepare_replicas_for_exchange(D, replicas, shared_data_url)
                print "Submitting %d replicas for Exchange run (dimension 2; cycle %d)" % (md_kernel.replicas, current_cycle)
                submitted_replicas = unit_manager.submit_units(exchange_replicas)
                unit_manager.wait_units()
          
                stop_time = datetime.datetime.utcnow()
                print "Cycle %d; dimension 2; Time to perform Exchange: %f" % (current_cycle, (stop_time - start_time).total_seconds())
                start_time = datetime.datetime.utcnow()

                matrix_columns = []
                for r in submitted_replicas:
                    d = str(r.stdout)
                    data = d.split()
                    matrix_columns.append(data)

                ##############################################
                # compose swap matrix from individual files
                ##############################################
                print "Composing swap matrix from individual files for all replicas"
                swap_matrix = self.compose_swap_matrix(replicas, matrix_columns)
            
                print "Performing exchange of salt concentrations"
                md_kernel.select_for_exchange(D, replicas, swap_matrix, current_cycle)

                stop_time = datetime.datetime.utcnow()
                print "Cycle %d; dimension 2; Post-processing time: %f" % (current_cycle, (stop_time - start_time).total_seconds())

        # end of loop
        d1_id_matrix = md_kernel.get_d1_id_matrix()
        temp_matrix = md_kernel.get_temp_matrix()
        
        d2_id_matrix = md_kernel.get_d2_id_matrix()
        salt_matrix = md_kernel.get_salt_matrix()

        print "Exchange matrix of replica id's for d1 (temperature) exchange: "
        print d1_id_matrix

        print "Change in temperatures for each replica: "
        print temp_matrix

        print "Exchange matrix of replica id's for d2 (salt concentration) exchange: "
        print d2_id_matrix

        print "Change in salt concentration for each replica: "
        print salt_matrix

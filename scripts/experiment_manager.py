import eigenhand_db_tools
import generation_manager
import eigenhand_db_objects
import server_list
import time
import remote_dispatcher
import atr
import eigenhand_genetic_algorithm
import examine_database
import os
import eigenhand_db_interface

class ExperimentManager(object):
    def __init__(self, num_ga_iters, num_atr_iters, task_model_list, task_prototype,
                 trials_per_task, eval_functor, db_interface, start_ga_iter = 0,
                 server_dict = server_list.clic_lab_dict, experiment_name = "default"):
        """
        @param num_ga_iters - The number of genetic algorithm generations to run
        @param num_atr_iters - The number of ATR iterations to run for each GA generation
        @param task_model_list - A list of TaskModels used to set up the database planner
        @param task_prototype - A prototype Task object that defines the trial specification(i.e. length and type)
        @param trials_per_task - The number of planning jobs to run for each object/hand pair per planning iteration. Results from each should look fairly unique.
        @param eval_functor - The function to use when evaluating hand fitness in the genetic algorithm
        @param db_interface - The database interface to use. Assumed to be initialized with a starting set of 0th generation hands
        @param starting_ga_iter - The generation to start from.
        @param server_dict - A dictionary whose keys are server urls that will be filled with
                             Servers as connections are made
        """
        self.task_prototype = task_prototype
        self.task_model_list = task_model_list
        self.num_ga_iters = num_ga_iters
        self.num_atr_iters = num_atr_iters
        self.eval_functor = eval_functor
        self.db_interface = db_interface
        self.starting_ga_iter = 0
        self.trials_per_task = trials_per_task
        self.gm = []
        self.server_dict = server_dict
        self.experiment_name = experiment_name
        self.e_list = dict()
        self.rd = []       #self.score_array = numpy.array([4,0])
        


    def get_current_ga_iteration(self):

        if not self.gm:
            error("ExperimentManager::get_current_ga::no_generation_manager","Error: Generation manager not initialized!")

        return self.gm.generation//self.get_generations_per_ga_iter()

    def get_generations_per_ga_iter(self):
        """
        @brief The generations of the gm counts the number of times a new set of hands is generated. This happens
        num_atr_iters times for each round of ATR and one additional time to generate the new hands for the GA
        totalling num_atr_itrs + 1 per each round of GA
        """
        return self.num_atr_iters + 1

    def get_last_ga_generation(self):
        """
        @brief Get the number of the last generation number of hands that were generated by a genetic algorithm, as opposed to ATR
        """
        ga_iter = self.get_current_ga_iteration()
        ga_generation = self.gm.generation//self.get_generations_per_ga_iter()
        return ga_generation

    def initialize_generation_manager(self):
        """
        @brief Create the generation manager that will be used in this experiment
        """
        return generation_manager.GenerationManager(self.db_interface, self.task_model_list,
                                                    self.starting_ga_iter*self.get_generations_per_ga_iter(),
                                                    self.task_prototype.task_time, self.trials_per_task,
                                                    self.task_prototype.task_type_id,
                                                    self.eval_functor)


    def output_current_status(self):
        filename = '/var/www/eigenhand_project/results'
        self.e_list.update(examine_database.get_e_list(self.gm, [], self.eval_functor))
        score_array = examine_database.e_list_to_score_array(self.e_list)
        examine_database.plot_elist_vs_gen(score_array, filename)


    def run_remote_dispatcher_tasks(self):
        """
        @brief Run the tasks on a cluster using the RemoteDispatcher framework developed for this project.

        """
        #Record the start time
        t = time.time()
        r = 0
        #Test if there are jobs available to do.
        job_num = eigenhand_db_tools.get_num_unlaunched_jobs(self.db_interface)

        #Try to run a new remote dispatcher loop as long as there are unfinished jobs
        while job_num > 2:
            print r
            r += 1
            #Blocks until time runs out or all jobs are finished.
            self.rd.run()
            #Reset any incomplete jobs. These are essentially jobs that we have lost connection with and cannot be
            #relied upon to terminate.
            self.db_interface.reset_incompletes()
            #See how many jobs are still undone.
            job_num = eigenhand_db_tools.get_num_unlaunched_jobs(self.db_interface)
        #If we only have a few stragglers, just stop trying -- We don't really need all of them to exit cleanly,
        #and it is easier to fail gracefully than try to handle every error.
        self.db_interface.set_incompletes_as_error()
        print "done.  Time %f \n"%(time.time() - t)


    def kill_existing(self):
        rd_list = [remote_dispatcher.RemoteServer(server, []) for server in self.server_dict.keys()]
        [rd.kill_previous() for rd in rd_list]
        [rd.collect_subprocesses() for rd in rd_list]
            

    def get_grasp_file(self, generation_number):
        '''
        @brief generates a simplistic filename for a specified generation, using the experiment experiment_name
        '''
        return "/data/%s_generation_%i"%(self.experiment_name, generation_number)

    def backup_grasps(self, generation):
        self.db_interface.incremental_backup(self.get_grasp_file(generation), ['grasp'])
        self.db_interface.clear_grasp_table()

    def restore_grasps(self, generation):
        d = {'grasp' : self.get_grasp_file(generation)+'_grasp'}
        self.db_interface.incremental_restore(d)

    def backup_hands(self):
        self.db_interface.incremental_backup('/data/%s'%(self.experiment_name),['hand','finger'])

    def restore_hands(self):
        d = {'finger':'/data/%s_%s'%(self.experiment_name,'finger'),'hand':'/data/%s_hand'%(self.experiment_name)}
        self.db_interface.incremental_restore(d)

    def restore_all_grasps(self):
        gen = 0
        print 'restoring all grasps \n'
        for gen in xrange(self.num_ga_iters * (self.num_atr_iters + 1) + 1):
            if os.path.exists(self.get_grasp_file(gen)+'_grasp'):
                print 'file exists %i \n'%(gen)
                self.starting_ga_iter = gen//(self.num_atr_iters + 1)
                try:
                    self.restore_grasps(gen)
                    
                except Exception as e:
                    print e
                    self.db_interface.connection.commit()
                


    
    def restore_all(self):
        self.db_interface.reset_database()
        self.restore_hands()
        self.restore_all_grasps()

    def restore_to_new_dbase(self):
        self.db_interface.prepare_empty_db(self.experiment_name)
        self.db_interface = eigenhand_db_interface.EGHandDBaseInterface(self.experiment_name)
        self.restore_all()

    def drop_dbase(self):
        self.db_interface.drop_database(self.experiment_name)
        

    def run_experiment(self):
        """
        @brief Run the whole experiment. Does num_ga_iters genetic algorithm runs each containing num_atr iterations
        of ATR.
        """
        #initialize new generation manager to configure the database to start running.
        self.gm = self.initialize_generation_manager()
        self.gm.start_generation()

        #Build the new remote dispatcher and connect all the servers
        self.rd = remote_dispatcher.RemoteDispatcher(self.db_interface)
        self.rd.init_all_servers(self.server_dict)
        self.run_remote_dispatcher_tasks()

        #Run through a bunch of iterations
        num_total_iters = (self.num_ga_iters-self.starting_ga_iter)*self.num_atr_iters
        for iter_num in xrange(num_total_iters):
            #Get the resulting grasps for the latest generation of hands
            grasp_list = self.gm.get_all_grasps()
            self.output_current_status()

            #Pull out our generation numbers
            atr_gen_num = (iter_num)%(self.num_atr_iters+1)
            ga_gen_num = iter_num//(self.num_atr_iters+1)

            #Every num_atr_iters+1th iteration is a genetic swap
            if atr_gen_num == self.num_atr_iters + 1:
                #Run atr on the existing hand for the latest generation of grasps
                new_hand_list = atr.ATR_generation(grasp_list, self.gm.hands)
            else:
                #Generate new hands based on these grasps, scaling the variance of the mutations down linearly as the
                #generations progress.
                new_hand_list = eigenhand_genetic_algorithm.GA_generation(grasp_list, self.gm.hands, self.eval_functor, .5-.4/self.num_ga_iters*ga_gen_num)

            #Put the new hands in to the database.
            eigenhand_db_tools.insert_unique_hand_list(new_hand_list, self.db_interface)

            #Backup old grasps and remove them from the grasp table
            self.backup_grasps(self.gm.generation)

            #Run the planner to get grasps for the last set of hands
            self.gm.next_generation()

            #Run the planning jobs
            self.run_remote_dispatcher_tasks()


        self.backup_grasps(self.gm.generation)
        self.backup_hands()

        self.rd.kill_all_servers()

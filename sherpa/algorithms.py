from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from .hyperparameters import Hyperparameter
from .resultstable import ResultsTable
from .samplers import RandomGenerator,GridSearch
import math
import numpy as np
import abc

class AbstractAlgorithm(object):
    @abc.abstractmethod
    def next(self, results_table, pending):
        ''' 
        Abstract method implemented by Algorithms. Algorithm can assume
        that a hp combo that is emitted will be run by the mainloop --- 
        I.E. the mainloop/scheduler are responsible for scheduling 
        and error handling. 
        
        Input:
            results_table = Object of type ResultsTable.
            pending = List of run_id's which are currently running. 
        Output:
            'wait'
            OR
            'stop'
            OR
            run_id = Key for identifying model instance (row of results_table).
            hp     = Hyperparameter combination.
            epochs = Number of epochs to train for.
        '''
        return

class Iterate(AbstractAlgorithm):
    '''
    Simply iterate over all combinations in discrete hp space, then stop.
    '''
    def __init__(self, epochs=1, hp_ranges=[]):
        '''
        Accepts hp_ranges as dictionary mapping hp names to lists.
        '''
        self.epochs  = epochs
        if isinstance(hp_ranges, dict):
            self.hp_ranges = [Hyperparameter.fromlist(name, choices) for (name,choices) in hp_ranges.items()]
        else:
            self.hp_ranges      = hp_ranges
        self.sampler = GridSearch(self.hp_ranges) # Iterate over all combinations of hp.
        self.count = 0    

    def next(self, results_table, pending):
        '''
        Examine current results and produce next experiment.
        Valid return values:
        1) run_id, hp, epochs: Tells main loop to start this experiment.
        2) 'wait': Signal to main loop that we are waiting.
        3) 'stop': Signal to main loop that we are finished.
        '''
        assert isinstance(results_table, ResultsTable)
        assert isinstance(pending, list)
        assert isinstance(len(pending), int)
        try:
            self.count += 1
            run_id = '1_{}'.format(self.count)
            return run_id, self.sampler.next(), self.epochs
        except StopIteration:
            return 'stop'
        

class RandomSearch(AbstractAlgorithm):
    """
    Random Search over hyperparameter space.
    """
    def __init__(self, samples, epochs, hp_ranges):
        self.samples        = samples
        self.epochs         = epochs
        if isinstance(hp_ranges, dict):
            self.hp_ranges = [Hyperparameter.fromlist(name, choices) in name,choices in hp_ranges.items()]
        else:
            self.hp_ranges      = hp_ranges
        self.sampler   = RandomGenerator(hp_ranges)

        print('Sampling %d random hp combinations from %d dimensions.' % (
            samples, len(hp_ranges)))

    def next(self, results_table, pending):
        '''
        Examine current results and produce next experiment.
        Valid return values:
        1) run_id, hp, epochs: Tells main loop to start this experiment.
        2) 'wait': Signal to main loop that we are waiting.
        3) 'stop': Signal to main loop that we are finished.
        '''
        assert isinstance(results_table, ResultsTable)
        assert isinstance(pending, list)
        df     = results_table.get_table() # Pandas df
        assert isinstance(df.shape[0], int)
        assert isinstance(len(pending), int)
        run_id = '1_%d' % (len(pending)+df.shape[0]) # Results table requires run_ids in this form.
        if df.shape[0] == self.samples and len(pending) == 0:
            return 'stop'
        elif len(pending)+df.shape[0] >= self.samples:
            return 'wait'
        else:
            return run_id, self.sampler.next(), self.epochs

class Hyperhack(AbstractAlgorithm):
    '''
    Successive halving variant. 
    Peter 2017
    '''
    def __init__(self, samples, epochs_per_stage, stages, sampler=RandomGenerator, survival=0.5, hp_ranges={},  constraints=[]):
        self.samples     = samples # Initial number of samples.
        self.survival    = survival # Value in [0,1], population is reduced to this amount at each stage.
        self.epochs_per_stage = epochs_per_stage
        self.stages      = stages
        self.hp_ranges   = hp_ranges
        #if sampler is None:
        #    sampler = RandomGenerator
        self.sampler = sampler(hp_ranges) # Initial sampling method for hyperparameters.
        
        # State of the algorithm.
        self.stage = 0
        self.population = []
        # Initialize population with hp combinations from generator that fit constraints.
        if len(constraints) == 0:
            self.population = [(('1_%d'%i), self.sampler.next()) for i in range(samples)] # Only one run.
        else:
            count = 0
            while count < samples:
                sample = self.sampler.next()
                sat = True
                for constraint in constraints:
                    sat = sat and constraint(sample)
                if sat:
                    self.population.append(('1_%d'%count, sample))
                    count += 1

    def next(self, results_table, pending):
        '''
        Examine current results and produce next experiment.
        Valid return values:
        1) run_id, hp, epochs: Tells main loop to start this experiment.
        2) 'wait': Signal to main loop that we are waiting.
        3) 'stop': Signal to main loop that we are finished.

        TODO: 
        1) The algorithm might want access to more information, e.g. the model and the full history.
           Therefore, I think the results table should include the modelfile and historyfile.

        '''
        if self.stage == 0 and len(self.population) == self.samples:
            print('\nStage %d/%d: %d samples, %d epochs per stage.' % (
                self.stage, self.stages, len(self.population),
                self.epochs_per_stage))

        if len(self.population) == 0:
            if len(pending) > 0:
                return 'wait' # Don't start next stage until everyone finishes previous stage.
            self.stage += 1
            if self.stage >= self.stages:
                return 'stop'
            else:
                k   = int(math.ceil(self.samples * self.survival**self.stage)) # Survivor number.
                run_ids = results_table.get_k_lowest_from_run(k, run=1) # Only 1 run.
                self.population = [(run_id, None) for run_id in run_ids] # Use empty hp to indicate restart training.
                print('\nStage %d/%d: %d survivors, %d epochs per stage.' % (self.stage, self.stages, k, self.epochs_per_stage))
                # Display best so far.
                run_id = results_table.get_k_lowest_from_run(k=1, run=1)[0]
                best   = {'ID':run_id}
                for k in ['Loss', 'Epochs', 'Hparams']:
                    best[k] = results_table.get(run_id=run_id, parameter=k)
                print('Best loss:%0.4f epochs:%d id:%s hp:%s' % (best['Loss'], best['Epochs'], run_id, best['Hparams']))

        run_id, hp = self.population.pop(0)
        return run_id, hp, self.epochs_per_stage

#
# class Hyperband():
#     '''
#     Hyperband
#     '''
#     def __init__(self, R, eta, hp_ranges, max_concurrent=10):
#         self.R = R
#         self.eta = eta
#         self.hp_ranges = hp_ranges
#         self.sampler = RandomGenerator(hp_ranges)
#         self.max_concurrent = max_concurrent
#
#         # Visualize schedule.
#         total_epochs = visualize_hyperband_params(R=self.R, eta=self.eta)
#
#         # State variables.
#         log_eta = lambda x: math.log(x) / math.log(eta)
#         s_max = int(log_eta(R))
#         B = (s_max + 1) * R
#         self.s = 0
#         self.i = 0
#         self.j = 1 # range()
#
#     def next(self, results_table, pending):
#         '''
#         Examine current results and produce next experiment.
#         Valid return values:
#         1) run_id, hp, epochs: Tells main loop to start this experiment.
#         2) 'wait': Signal to main loop that we are waiting.
#         3) 'stop': Signal to main loop that we are finished.
#         '''
#
#         if len(pending) >= max_concurrent:
#             return 'wait'
#
#         log_eta = lambda x: math.log(x) / math.log(eta)
#         s_max = int(log_eta(R))
#         B = (s_max + 1) * R
#
#         for s in reversed(range(s_max + 1)):
#             n = int(math.ceil(B / R / (s + 1) * eta ** s))
#             r = R * eta ** (-s)
#
#             for i in range(s + 1):
#                 n_i = int(n * eta ** (-i))
#                 r_i = int(round(r * eta ** (i)))
#
#                 run = s_max - s + 1
#                 if i == 0:
#                     for j in range(1, n_i+1):
#                         if s==s_max and i==0 and j==1:
#                             self.estimate_time(self.scheduler.submit,
#                                                {'run_id': '{}_{}'.format(run,j),
#                                                 'hp':
#                                                     self.hparam_gen.next(),
#                                                 'epochs': r_i},
#                                                total_epochs=total_epochs,
#                                                r_i=r_i)
#
#                         else:
#                             self.scheduler.submit(run_id='{}_{}'.format(run,
#                                                                         j),
#                                                   hp=self.hparam_gen.next(),
#                                                   epochs=r_i)
#                 else:
#                     for run_id in self.results_table.get_k_lowest_from_run(n_i,
#                                                                         run):
#                         self.scheduler.submit(run_id=run_id, epochs=r_i)
#
#         return self.results_table.get_table()
#
#     @staticmethod
#     def estimate_time(f, args, total_epochs, r_i):
#         time, result = timedcall(f, args)
#
#         secs = total_epochs * time / r_i
#         hrs = secs // 3600
#         mins = (secs % 3600) // 60
#         print('-' * 100)
#         print('\nThe complete Hyperband optimization is '
#               'estimated to take {}hrs and {} '
#               'mins\n'.format(
#             hrs, mins))
#         print('-' * 100)
#

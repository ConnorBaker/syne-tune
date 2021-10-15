import argparse
import logging

from benchmark_factory import supported_benchmarks, benchmark_factory

logger = logging.getLogger(__name__)

__all__ = ['parse_args',
           'make_searcher_and_scheduler',
           'estimator_kwargs_from_benchmark_params']


def parse_args(allow_lists_as_values=True):
    """
    Argument parser for CLI. Normally, this parameterizes a single experiment.
    But if `allow_lists_as_values == True`, certain arguments admit lists as
    values. In this case, experiments of all combinations of values (Cartesian
    product) are launched.

    :param allow_lists_as_values: See above
    :return: params dict. Note that if an argument added to the parser is not
        provided a value for, it is contained in the dict with value None

    """
    parser = argparse.ArgumentParser(
        description='Asynchronous Hyperparameter Optimization')
    # We parse the CL args twice. The first pass parses all global arguments
    # (not specific to the benchmark). From that pass, we know what the
    # benchmark is. In a second pass, we parse additional benchmark-specific
    # arguments, as defined in the default_params for the benchmark.
    if allow_lists_as_values:
        allow_list = dict(nargs='+')
    else:
        allow_list = dict()

    if allow_lists_as_values:
        parser.add_argument('--argument_groups', type=str,
                            help='Specify groups of list arguments, separated '
                                 'by |. Arguments in a group are iterated '
                                 'over together')
    # Note: The benchmark cannot be a list argument, since it can define its
    # own CL arguments
    parser.add_argument('--benchmark_name', type=str,
                        default='mlp_fashionmnist',
                        choices=supported_benchmarks(),
                        help='Benchmark to run experiment on')
    parser.add_argument('--skip_initial_experiments', type=int, default=0,
                        help='When multiple experiments are launched (due to '
                             'list arguments), this number of initial '
                             'experiments are skipped')
    parser.add_argument('--backend', type=str, default='local',
                        choices=('local', 'sagemaker', 'simulated'),
                        help='Backend for training evaluations')
    parser.add_argument('--local_tuner', action='store_true',
                        help='Run tuning experiment locally? Otherwise, it is '
                             'run remotely (which allows to run multiple '
                             'tuning experiments in parallel)')
    parser.add_argument('--run_id', type=int,
                        help='Identifier to distinguish between runs '
                             '(nonnegative integers)',
                        **allow_list)
    parser.add_argument('--num_runs', type=int,
                        help='Number of repetitions, with run_id 0, 1, ...'
                             'Only if run_id not given (ignored otherwise)')
    parser.add_argument('--random_seed_offset', type=int,
                        help='Master random seed is this plus run_id, modulo '
                             '2 ** 32. Drawn at random if not given')
    parser.add_argument('--instance_type', type=str,
                        help='SageMaker instance type for workers',
                        **allow_list)
    parser.add_argument('--tuner_instance_type', type=str,
                        default='ml.c5.xlarge',
                        help='SageMaker instance type for tuner (only for '
                             'sagemaker backend and remote tuning)',
                        **allow_list)
    parser.add_argument('--num_workers', type=int,
                        help='Number of workers (parallel evaluations)',
                        **allow_list)
    parser.add_argument('--image_uri', type=str,
                        help='URI of Docker image (sagemaker backend)')
    parser.add_argument('--sagemaker_execution_role', type=str,
                        help='SageMaker execution role (sagemaker backend)')
    parser.add_argument('--experiment_name', type=str,
                        help='Experiment name (used as job_name_prefix in '
                             'sagemaker backend)')
    parser.add_argument('--no_debug_log', action='store_true',
                        help='Switch off verbose logging')
    parser.add_argument('--debug_log_level', action='store_true',
                        help='Set logging level to DEBUG (default is INFO)')
    parser.add_argument('--no_tuner_logging', action='store_true',
                        help='By default, the full tuning status is logged '
                             'in the tuning loop every --print_update_interval'
                             ' secs. If this is set, this logging is suppressed')
    parser.add_argument('--enable_sagemaker_profiler', action='store_true',
                        help='Enable SageMaker profiler (this needs one '
                             'processing job for each training job')
    parser.add_argument('--no_experiment_subdirectory', action='store_true',
                        help='When storing results, do not use subdirectory '
                             'experiment_name')
    parser.add_argument('--cost_model_type', type=str,
                        help='Selects cost model of benchmark',
                        **allow_list)
    parser.add_argument('--scheduler', type=str, default='fifo',
                        help='Scheduler name',
                        **allow_list)
    parser.add_argument('--searcher', type=str,
                        help='Searcher name',
                        **allow_list)
    # This is a legacy argument, previously needed for 'nasbench201' benchmark,
    # but its better to use 'nasbench201_XYZ' for 'benchmark_name', where XYZ
    # is 'dataset_name'.
    parser.add_argument('--dataset_name', type=str,
                        help='Additional argument for some benchmarks')
    parser.add_argument('--results_update_interval', type=int, default=300,
                        help='Results and tuner state are stored every this '
                             'many seconds')
    parser.add_argument('--print_update_interval', type=int, default=300,
                        help='Tuner status printed every this many seconds')
    parser.add_argument('--disable_checkpointing', action='store_true',
                        help='Disable checkpointing for training evaluations')
    parser.add_argument('--tuner_sleep_time', type=float, default=5,
                        help='Tuner tries to fetch new results every this '
                             'many seconds')
    parser.add_argument('--max_resource_level', type=int,
                        help='Largest resource level (e.g., epoch number) '
                             'for training evaluations',
                        **allow_list)
    parser.add_argument('--epochs', type=int,
                        help='Deprecated: Use max_resource_level instead',
                        **allow_list)
    parser.add_argument('--num_trials', type=int,
                        help='Maximum number of trials',
                        **allow_list)
    parser.add_argument('--scheduler_timeout', type=int,
                        help='Trials started until this cutoff time (in secs)',
                        **allow_list)
    parser.add_argument('--max_failures', type=int, default=1,
                        help='The tuning job terminates once this many '
                             'training evaluations failed',
                        **allow_list)
    parser.add_argument('--synchronous', action='store_true',
                        help='Run synchronous (instead of asynchronous) '
                             'scheduling: trials are started in batches of '
                             'size num_workers. Not currently implemented for '
                             'Hyperband scheduling.')
    parser.add_argument('--s3_bucket', type=str,
                        help='S3 bucket to write checkpoints and results to. '
                             'Defaults to default bucket of session')
    parser.add_argument('--no_gpu_rotation', action='store_true',
                        help='For local back-end on a GPU instance: By '
                             'default, trials are launched in parallel '
                             'on different GPU cores (GPU rotation). If '
                             'this is set, all GPU cores are used for a '
                             'single evaluation')
    # Arguments for scheduler
    parser.add_argument('--brackets', type=int,
                        help='Number of brackets in HyperbandScheduler',
                        **allow_list)
    parser.add_argument('--reduction_factor', type=int,
                        help='Reduction factor in HyperbandScheduler',
                        **allow_list)
    parser.add_argument('--grace_period', type=int,
                        help='Minimum resource level (e.g., epoch number) '
                             'in HyperbandScheduler',
                        **allow_list)
    parser.add_argument('--no_rung_system_per_bracket', action='store_true',
                        help='Parameter of HyperbandScheduler')
    parser.add_argument('--searcher_data', type=str,
                        help='Parameter of HyperbandScheduler',
                        **allow_list)
    # Arguments for bayesopt searcher
    parser.add_argument('--searcher_num_init_random', type=int,
                        help='Number of initial trials not chosen by searcher',
                        **allow_list)
    parser.add_argument('--searcher_num_init_candidates', type=int,
                        help='Number of random candidates scored to seed search',
                        **allow_list)
    parser.add_argument('--searcher_num_fantasy_samples', type=int,
                        help='Number of fantasy samples',
                        **allow_list)
    parser.add_argument('--searcher_resource_acq', type=str,
                        help='Determines how EI acquisition function is used '
                             '[bohb, first]',
                        **allow_list)
    parser.add_argument('--searcher_resource_acq_bohb_threshold', type=int,
                        help='Parameter for resource_acq == bohb',
                        **allow_list)
    parser.add_argument('--searcher_gp_resource_kernel', type=str,
                        help='Multi-task kernel for HyperbandScheduler',
                        **allow_list)
    parser.add_argument('--searcher_opt_skip_period', type=int,
                        help='Update GP hyperparameters only every (...) times',
                        **allow_list)
    parser.add_argument('--searcher_opt_skip_init_length', type=int,
                        help='Update GP hyperparameters every time until '
                             '(...) observations are done',
                        **allow_list)
    parser.add_argument('--searcher_opt_skip_num_max_resource',
                        action='store_true',
                        help='Update GP hyperparameters only when training '
                             'runs reach max_t')
    parser.add_argument('--searcher_opt_nstarts', type=int,
                        help='GP hyperparameter optimization restarted (...) '
                             'times',
                        **allow_list)
    parser.add_argument('--searcher_opt_maxiter', type=int,
                        help='Maximum number of iterations of GP '
                             'hyperparameter optimization',
                        **allow_list)
    parser.add_argument('--searcher_initial_scoring', type=str,
                        help='Scoring function to rank initial candidates '
                             'for seeding search [thompson_indep, acq_func]',
                        **allow_list)
    parser.add_argument('--searcher_issm_gamma_one', action='store_true',
                        help='Fix gamma parameter of ISSM to one?')
    parser.add_argument('--searcher_exponent_cost', type=float,
                        help='Exponent of cost term in cost-aware expected '
                             'improvement acquisition function',
                        **allow_list)

    # First pass: All global arguments
    # Why do we parse all global args here, and not just benchmark_name?
    # This is to make sure that the help option of the parser lists all
    # global arguments and their help strings.
    _params = parser.parse_known_args()[0]
    benchmark_name = _params.benchmark_name

    # Add benchmark-specific CL args (if any)
    # These are the ones listed in benchmark['default_params'], minus args which
    # are already global (i.e., added above)
    _, default_params = benchmark_factory({'benchmark_name': benchmark_name})
    help_str = f"Additional parameter for {benchmark_name} benchmark"
    have_extra_args = False
    for name, value in default_params.items():
        try:
            # We don't need to set defaults here
            parser.add_argument('--' + name, type=type(value), help=help_str)
            have_extra_args = True
        except argparse.ArgumentError:
            pass

    # Second pass: All args (global and benchmark-specific)
    if have_extra_args:
        params = vars(parser.parse_args())
    else:
        params = _params
    # Post-processing
    params['debug_log'] = not params['no_debug_log']
    del params['no_debug_log']
    params['rotate_gpus'] = not params['no_gpu_rotation']
    del params['no_gpu_rotation']
    params['enable_checkpointing'] = not params['disable_checkpointing']
    del params['disable_checkpointing']
    epochs = params.get('epochs')
    if params.get('max_resource_level') is None:
        if epochs is not None:
            logger.info("--epochs is deprecated, please use "
                        "--max_resource_level in the future")
            params['max_resource_level'] = epochs
    elif epochs is not None:
        logger.info("Both --max_resource_level and the deprecated "
                    "--epochs are set. The latter is ignored")
    if 'epochs' in params:
        del params['epochs']
    params['rung_system_per_bracket'] = not params['no_rung_system_per_bracket']

    return params


def _enter_not_none(dct, key, val, type=None):
    if type is None:
        type = str
    if val is not None:
        dct[key] = type(val)


def make_searcher_and_scheduler(params) -> (dict, dict):
    # Options for searcher
    search_options = dict()
    _enter_not_none(
        search_options, 'debug_log', params.get('debug_log'), type=bool)
    # Options for bayesopt searcher
    searcher_args = (
        ('num_init_random', int),
        ('num_init_candidates', int),
        ('num_fantasy_samples', int),
        ('resource_acq', str),
        ('resource_acq_bohb_threshold', int),
        ('gp_resource_kernel', str),
        ('opt_skip_period', int),
        ('opt_skip_init_length', int),
        ('opt_skip_num_max_resource', bool),
        ('opt_nstarts', int),
        ('opt_maxiter', int),
        ('initial_scoring', str),
        ('issm_gamma_one', bool),
        ('exponent_cost', float),
    )
    for name, tp in searcher_args:
        _enter_not_none(
            search_options, name, params.get('searcher_' + name), type=tp)

    # Options for scheduler
    scheduler = params['scheduler']
    random_seed_offset = params.get('random_seed_offset')
    if random_seed_offset is None:
        random_seed_offset = 0
    random_seed = (random_seed_offset + params['run_id']) % (2 ** 32)
    scheduler_options = {'random_seed': random_seed}
    _enter_not_none(
        scheduler_options, 'max_t', params.get('max_resource_level'),
        type=int)
    scheduler_args = (
        ('max_resource_attr', str),
    )
    if scheduler != 'fifo':
        # Only process these arguments for HyperbandScheduler
        prefix = 'hyperband_'
        assert scheduler.startswith(prefix)
        sch_type = scheduler[len(prefix):]
        _enter_not_none(scheduler_options, 'type', sch_type)
        scheduler_args = scheduler_args + (
            ('reduction_factor', int),
            ('grace_period', int),
            ('brackets', int),
            ('searcher_data', str),
            ('rung_system_per_bracket', bool),
        )
    for name, tp in scheduler_args:
        _enter_not_none(
            scheduler_options, name, params.get(name), type=tp)

    return search_options, scheduler_options


def estimator_kwargs_from_benchmark_params(default_params: dict) -> dict:
    keys = {
        'instance_type', 'framework', 'framework_version', 'pytorch_version'}
    result = {k: v for k, v in default_params.items() if k in keys}
    return result
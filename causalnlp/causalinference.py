# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/00_causalinference.ipynb (unless otherwise specified).

__all__ = ['CausalInferenceModel', 'metalearner_cls_dict', 'metalearner_reg_dict']

# Cell
import pandas as pd
pd.set_option('display.max_columns', 500)
import time

from .meta.tlearner import BaseTClassifier, BaseTRegressor
from .meta.slearner import BaseSClassifier, BaseSRegressor, LRSRegressor
from .meta.xlearner import BaseXClassifier, BaseXRegressor
from .meta.rlearner import BaseRClassifier, BaseRRegressor
from .meta.propensity import ElasticNetPropensityModel
from .meta.utils import NearestNeighborMatch, create_table_one
from scipy import stats
from lightgbm import LGBMClassifier, LGBMRegressor
import numpy as np
import warnings
from copy import deepcopy
from matplotlib import pyplot as plt
from .preprocessing import DataframePreprocessor

# from xgboost import XGBRegressor
# from causalml.inference.meta import XGBTRegressor, MLPTRegressor



metalearner_cls_dict = {'t-learner' : BaseTClassifier,
                        'x-learner' : BaseXClassifier,
                        'r-learner' : BaseRClassifier,
                         's-learner': BaseSClassifier}
metalearner_reg_dict = {'t-learner' : BaseTRegressor,
                        'x-learner' : BaseXRegressor,
                        'r-learner' : BaseRRegressor,
                        's-learner' : BaseSRegressor}

class CausalInferenceModel:
    """Infers causality from the data contained in `df` using a metalearner.


    Usage:

    ```python
    >>> cm = CausalInferenceModel(df,
                                  treatment_col='Is_Male?',
                                  outcome_col='Post_Shared?', text_col='Post_Text',
                                  ignore_cols=['id', 'email'])
        cm.fit()
    ```

    **Parameters:**

    * **df** : pandas.DataFrame containing dataset
    * **metalearner_type** : metalearner model to use. One of {'t-learner', 's-learner', 'x-learner', 'r-learner'} (Default: 't-learner')

    * **treatment_col** : treatment variable; column should contain binary values: 1 for treated, 0 for untreated.
    * **outcome_col** : outcome variable; column should contain the categorical or numeric outcome values
    * **text_col** : (optional) text column containing the strings (e.g., articles, reviews, emails).
    * **ignore_cols** : columns to ignore in the analysis
    * **include_cols** : columns to include as covariates (e.g., possible confounders)
    * **treatment_effect_col** : name of column to hold causal effect estimations.  Does not need to exist.  Created by CausalNLP.
    * **learner** : an instance of a custom learner.  If None, a default LightGBM will be used.
        # Example
         learner = LGBMClassifier(num_leaves=1000)
    * **effect_learner**: used for x-learner/r-learner and must be regression model
    * **min_df** : min_df parameter used for text processing using sklearn
    * **max_df** : max_df parameter used for text procesing using sklearn
    * **ngram_range**: ngrams used for text vectorization. default: (1,1)
    * **stop_words** : stop words used for text processing (from sklearn)
    * **verbose** : If 1, print informational messages.  If 0, suppress.
    """
    def __init__(self,
                 df,
                 metalearner_type='t-learner',
                 treatment_col='treatment',
                 outcome_col='outcome',
                 text_col=None,
                 ignore_cols=[],
                 include_cols=[],
                 treatment_effect_col = 'treatment_effect',
                 learner = None,
                 effect_learner=None,
                 min_df=0.05,
                 max_df=0.5,
                 ngram_range=(1,1),
                 stop_words='english',
                 verbose=1):
        """
        constructor
        """
        metalearner_list = list(metalearner_cls_dict.keys())
        if metalearner_type not in metalearner_list:
            raise ValueError('metalearner_type is required and must be one of: %s' % (metalearner_list))
        self.te = treatment_effect_col # created
        self.metalearner_type = metalearner_type
        self.v = verbose
        self.df = df.copy()


        # these are auto-populated by preprocess method
        self.x = None
        self.y = None
        self.treatment = None

        # preprocess
        self.pp = DataframePreprocessor(treatment_col = treatment_col,
                                       outcome_col = outcome_col,
                                       text_col=text_col,
                                       include_cols=include_cols,
                                       ignore_cols=ignore_cols,
                                       verbose=self.v)
        self.df, self.x, self.y, self.treatment = self.pp.preprocess(self.df,
                                                                     training=True,
                                                                     min_df=min_df,
                                                                     max_df=max_df,
                                                                     ngram_range=ngram_range,
                                                                     stop_words=stop_words)

        # setup model
        self.model = self._create_metalearner(metalearner_type=self.metalearner_type,
                                             supplied_learner=learner,
                                             supplied_effect_learner=effect_learner)



    def _create_metalearner(self, metalearner_type='t-learner',
                            supplied_learner=None, supplied_effect_learner=None):
        # set learner
        default_learner = None
        if self.pp.is_classification:
            default_learner = LGBMClassifier()
        else:
            default_learner =  LGBMRegressor()
        default_effect_learner = LGBMRegressor()
        learner = default_learner if supplied_learner is None else supplied_learner
        effect_learner = default_effect_learner if supplied_effect_learner is None else\
                         supplied_effect_learner

        # set metalearner
        metalearner_class = metalearner_cls_dict[metalearner_type] if self.pp.is_classification \
                                                                   else metalearner_reg_dict[metalearner_type]
        if metalearner_type in ['t-learner', 's-learner']:
            model = metalearner_class(learner=learner,control_name=0)
        elif metalearner_type in ['x-learner']:
            model = metalearner_class(
                                      control_outcome_learner=deepcopy(learner),
                                      treatment_outcome_learner=deepcopy(learner),
                                      control_effect_learner=deepcopy(effect_learner),
                                      treatment_effect_learner=deepcopy(effect_learner),
                                      control_name=0)
        else:
            model = metalearner_class(outcome_learner=deepcopy(learner),
                                      effect_learner=deepcopy(effect_learner),
                                      control_name=0)
        return model


    def fit(self):
        """
        Fits a causal inference model and estimates outcome
        with and without treatment for each observation.
        """
        print("start fitting causal inference model")
        start_time = time.time()
        self.model.fit(self.x.values, self.treatment.values, self.y.values)
        preds = self._predict(self.x)
        self.df[self.te] = preds
        print("time to fit causal inference model: ",-start_time + time.time()," sec")
        return self

    def predict(self, df):
        """
        Estimates the treatment effect for each observation in `df`.
        The DataFrame represented by `df` should be the same format
        as the one supplied to `CausalInferenceModel.__init__`.
        """
        _, x, _, _ = self.pp.preprocess(df, training=False)
        return self._predict(x)


    def _predict(self, x):
        """
        Estimates the treatment effect for each observation in `x`,
        where `x` is an **un-preprocessed** DataFrame of Numpy array.
        """
        if isinstance(x, pd.DataFrame):
            return self.model.predict(x.values)
        else:
            return self.model.predict(x)

    def estimate_ate(self, bool_mask=None):
        """
        Estimates the treatment effect for each observation in
        `self.df`.
        """
        df = self.df if bool_mask is None else self.df[bool_mask]
        a = df[self.te].values
        mean = np.mean(a)
        return {'ate' : mean}


    def interpret(self, plot=False, method='feature_importance'):
        """
        Returns feature importances of treatment effect model.
        The method parameter must be one of {'feature_importance', 'shap_values'}
        """
        tau = self.df[self.te]
        feature_names = self.x.columns.values
        if plot:
            if method=='feature_importance':
                fn = self.model.plot_importance
            elif method == 'shap_values':
                fn = self.model.plot_shap_values
            else:
                raise ValueError('Unknown method: %s' % method)
        else:
            if method=='feature_importance':
                fn = self.model.get_importance
            elif method == 'shap_values':
                fn = self.model.get_shap_values
            else:
                raise ValueError('Unknown method: %s' % method)
        return fn(X=self.x, tau=tau, features = feature_names)


    def _minimize_bias(self, caliper = None):
        """
        minimize bias (experimental/untested)
        """

        print('-------Start bias minimization procedure----------')
        start_time = time.time()
        #Join x, y and treatment vectors
        df_match = self.x.merge(self.treatment,left_index=True, right_index=True)
        df_match = df_match.merge(self.y, left_index=True, right_index=True)

        #buld propensity model. Propensity is the probability of raw belongs to control group.
        pm = ElasticNetPropensityModel(n_fold=3, random_state=42)

        #ps - propensity score
        df_match['ps'] = pm.fit_predict(self.x, self.treatment)

        #Matching model object
        psm = NearestNeighborMatch(replace=False,
                       ratio=1,
                       random_state=423,
                       caliper=caliper)

        ps_cols = list(self.pp.feature_names_one_hot)
        ps_cols.append('ps')

        #Apply matching model
        #If error, then sample is unbiased and we don't do anything
        self.flg_bias = True
        self.df_unbiased = psm.match(data=df_match, treatment_col=self.pp.treatment_col,score_cols=['ps'])
        self.x_unbiased = self.df_unbiased[self.x.columns]
        self.y_unbiased = self.df_unbiased[self.pp.outcome_col]
        self.treatment_unbiased = self.df_unbiased[self.pp.treatment_col]
        print('-------------------MATCHING RESULTS----------------')
        print('-----BEFORE MATCHING-------')
        print(create_table_one(data=df_match,
                                treatment_col=self.pp.treatment_col,
                                features=list(self.pp.feature_names_one_hot)))
        print('-----AFTER MATCHING-------')
        print(create_table_one(data=self.df_unbiased,
                                treatment_col=self.pp.treatment_col,
                                features=list(self.pp.feature_names_one_hot)))
        return self.df_unbiased

    def _predict_shap(self, x):
        return self._predict(x)

    def explain(self, df, row_index=None, row_num=0, background_size=50, nsamples=500):
        """
        Explain the treatment effect estimate of a single observation using SHAP.


        **Parameters:**
          - **df** (pd.DataFrame): a pd.DataFrame of test data is same format as original training data DataFrame
          - **row_num** (int): raw row number in DataFrame to explain (default:0, the first row)
          - **background_size** (int): size of background data (SHAP parameter)
          - **nsamples** (int): number of samples (SHAP parameter)
        """
        try:
            import shap
        except ImportError:
            msg = 'The explain method requires shap library. Please install with: pip install shap. '+\
                    'Conda users should use this command instead: conda install -c conda-forge shap'
            raise ImportError(msg)

        f = self._predict_shap

        # preprocess dataframe
        _, df_display, _, _ = self.pp.preprocess(df.copy(), training=False)


        # select row
        df_display_row = df_display.iloc[[row_num]]
        r_key = 'row_num'
        r_val = row_num

        # shap
        explainer = shap.KernelExplainer(f, self.x.iloc[:background_size,:])
        shap_values = explainer.shap_values(df_display_row, nsamples=nsamples, l1_reg='aic')
        expected_value = explainer.expected_value

        if not np.issubdtype(type(explainer.expected_value), np.floating):
            expected_value = explainer.expected_value[0]
        if type(shap_values) == list:
            shap_values = shap_values[0]
        plt.show(shap.force_plot(expected_value, shap_values, df_display_row, matplotlib=True))


    def get_required_columns(self):
        """
        Returns required columns that must exist in any DataFrame supplied to `CausalInferenceModel.predict`.
        """
        treatment_col = self.pp.treatment_col
        other_cols = self.pp.feature_names
        result = [treatment_col] + other_cols
        if self.pp.text_col: result.append(self.pp.text_col)
        return result


    def tune_and_use_default_learner(self, split_pct=0.2, random_state=314, scoring=None):
        """
        Tunes the hyperparameters of a default LightGBM model, replaces `CausalInferenceModel.learner`,
        and returns best parameters.
        Should be invoked **prior** to running `CausalInferencemodel.fit`.
        If `scoring` is None, then 'roc_auc' is used for classification and 'negative_mean_squared_error'
        is used for regresssion.
        """
        from sklearn.model_selection import train_test_split
        X_train, X_test, y_train, y_test = train_test_split(self.x.values, self.y.values,
                                                            test_size=split_pct,
                                                            random_state=random_state)

        fit_params={"early_stopping_rounds":30,
                    "eval_metric" : 'auc',
                    "eval_set" : [(X_test,y_test)],
                    'eval_names': ['valid'],
                    'verbose': 100,
                    'categorical_feature': 'auto'}


        from scipy.stats import randint as sp_randint
        from scipy.stats import uniform as sp_uniform
        param_test ={'num_leaves': sp_randint(6, 750),
                     'min_child_samples': sp_randint(20, 500),
                     'min_child_weight': [1e-5, 1e-3, 1e-2, 1e-1, 1, 1e1, 1e2, 1e3, 1e4],
                     'subsample': sp_uniform(loc=0.2, scale=0.8),
                     'colsample_bytree': sp_uniform(loc=0.4, scale=0.6),
                     'reg_alpha': [0, 1e-1, 1, 2, 5, 7, 10, 50, 100],
                     'reg_lambda': [0, 1e-1, 1, 5, 10, 20, 50, 100]}
        n_HP_points_to_test = 100
        if self.pp.is_classification:
            learner_type = LGBMClassifier
            scoring = 'roc_auc' if scoring is None else scoring
        else:
            learner_type =  LGBMRegressor
            scoring = 'neg_mean_squared_error' if scoring is None else scoring
        clf = learner_type(max_depth=-1, random_state=random_state, silent=True,
                         metric='None', n_jobs=4, n_estimators=5000)
        from sklearn.model_selection import RandomizedSearchCV, GridSearchCV
        gs = RandomizedSearchCV(
                estimator=clf, param_distributions=param_test,
                n_iter=n_HP_points_to_test,
                scoring='roc_auc',
                cv=3,
                refit=True,
                random_state=random_state,
                verbose=True)

        gs.fit(X_train, y_train, **fit_params)
        print('Best score reached: {} with params: {} '.format(gs.best_score_, gs.best_params_))
        best_params = gs.best_params_
        self.learner = learner_type(**best_params)
        return best_params

    def evaluate_robustness(self, sample_size=0.8):
        """
        Evaluates robustness on four sensitivity measures (see CausalML package for details on these methods):
        - **Placebo Treatment**: ATE should become zero.
        - **Random Cause**: ATE should not change.
        - **Random Replacement**: ATE should not change.
        - **Subset Data**: ATE should not change.
        """
        from .meta.sensitivity import Sensitivity
        data_df = self.x.copy()
        t_col = 'CausalNLP_t'
        y_col = 'CausalNLP_y'
        data_df[t_col] = self.treatment
        data_df[y_col] = self.y
        sens_x = Sensitivity(df=data_df,
                             inference_features=self.x.columns.values,
                             p_col=None,
                             treatment_col=t_col, outcome_col=y_col,
                             learner=self.model)
        df = sens_x.sensitivity_analysis(methods=['Placebo Treatment',
                                                  'Random Cause',
                                                  'Subset Data',
                                                  'Random Replace',
                                                    ],sample_size=sample_size)
        df['Distance from Desired (should be near 0)'] = np.where(df['Method']=='Placebo Treatment',
                                                             df['New ATE']-0.0,
                                                             df['New ATE']-df['ATE'])

        #df['Method'] = np.where(df['Method']=='Random Cause', 'Random Add', df['Method'])
        return df
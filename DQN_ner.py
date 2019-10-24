import sys
import math
sys.path.insert(1, './src')
import argparse
from game_ner import NERGame
from robot import RobotCNNDQN
import numpy as np
import helpers
import tensorflow as tf
import random
import pickle
from tagger import CRFTagger
import warnings; warnings.simplefilter('ignore')
print (tf.__version__)

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--agent', help="require a decision agent")
    parser.add_argument('--episode', help="require a maximum number of playing the game")
    parser.add_argument('--budget', help="requrie a budget for annotating")
    parser.add_argument('--train', help="training phase")
    parser.add_argument('--test', help="testing phase")
    args = parser.parse_args()
    
    global AGENT, MAX_EPISODE, BUDGET, TRAIN_LANG, TEST_LANG
    AGENT = args.agent
    MAX_EPISODE = int(args.episode)
    BUDGET = int(args.budget)
    # load the train data: source languages
    parts = args.train.split(";")
    if len(parts) % 5 != 0:
        print ("Wrong inputs of training")
        raise SystemExit
    global TRAIN_LANG_NUM
    TRAIN_LANG_NUM = len(parts) / 5
    for i in range(TRAIN_LANG_NUM):
        lang_i = i * 5
        train = parts[lang_i + 0]
        test = parts[lang_i + 1]
        dev = parts[lang_i + 2]
        emb = parts[lang_i + 3]
        tagger = parts[lang_i + 4]
        TRAIN_LANG.append((train, test, dev, emb, tagger))
    # load the test data: target languages
    parts = args.test.split(";")
    if len(parts) % 5 != 0:
        print ("Wrong inputs of testing")
        raise SystemExit
    global TEST_LANG_NUM
    TEST_LANG_NUM = len(parts) / 5
    for i in range(TEST_LANG_NUM):
        lang_i = i * 5
        train = parts[lang_i + 0]
        test = parts[lang_i + 1]
        dev = parts[lang_i + 2]
        emb = parts[lang_i + 3]
        tagger = parts[lang_i + 4]
        TEST_LANG.append((train, test, dev, emb, tagger))

def initialise_game(train_file, test_file, dev_file, emb_file, budget):
    # Load data
    print("Loading data ..")
    train_x, train_y, train_lens = helpers.load_data2labels(train_file)
    test_x, test_y, test_lens = helpers.load_data2labels(test_file)
    dev_x, dev_y, dev_lens = helpers.load_data2labels(dev_file)

    print("Processing data")
    # build vocabulary
    max_len = FLAGS.flag_values_dict()['max_seq_len']
    print ("Max document length:", max_len)
    vocab_processor = tf.contrib.learn.preprocessing.VocabularyProcessor(
        max_document_length=max_len, min_frequency=1)
    # vocab = vocab_processor.vocabulary_ # start from {"<UNK>":0}
    train_idx = np.array(list(vocab_processor.fit_transform(train_x)))
    dev_idx = np.array(list(vocab_processor.fit_transform(dev_x)))
    vocab = vocab_processor.vocabulary_
    vocab.freeze()
    test_idx = np.array(list(vocab_processor.fit_transform(test_x)))

    # build embeddings
    vocab = vocab_processor.vocabulary_
    vocab_size = FLAGS.flag_values_dict()['max_vocab_size']
    w2v = helpers.load_crosslingual_embeddings(emb_file, vocab, vocab_size)

    # prepare story
    story = [train_x, train_y, train_idx]
    print ("The length of the story ", len(train_x), " ( DEV = ", len(dev_x), " TEST = ", len(test_x), " )")
    test = [test_x, test_y, test_idx]
    dev = [dev_x, dev_y, dev_idx]
    # load game
    print("Loading game ..")
    game = NERGame(story, test, dev, max_len, w2v, budget)
    return game

def play_ner():
    actions = 2
    global AGENT
    robot = RobotCNNDQN(AGENT, actions)
    
#     if AGENT == "random":
#         robot = RobotRandom(actions)
#     elif AGENT == "DQN":
#         robot = RobotDQN(actions)
#     elif AGENT == "CNNDQN":
#         robot = RobotCNNDQN(actions)
#     else:
#         print ("** There is no robot.")
#         raise SystemExit

    global TRAIN_LANG, TRAIN_LANG_NUM, BUDGET
    for i in range(TRAIN_LANG_NUM):
        train = TRAIN_LANG[i][0]
        test = TRAIN_LANG[i][1]
        dev = TRAIN_LANG[i][2]
        emb = TRAIN_LANG[i][3]
        tagger = TRAIN_LANG[i][4]
        # initilise a NER game
        game = initialise_game(train, test, dev, emb, BUDGET)
        # initialise a decision robot
        robot.initialise(game.max_len, game.w2v)
#         robot.update_embeddings(game.w2v)
        # tagger
        model = CRFTagger(tagger)
        # play game
        episode = 1
        print(">>>>>> Playing game ..")
        while episode <= MAX_EPISODE:
            print ('>>>>>>> Current game round ', episode, 'Maximum ', MAX_EPISODE)
            observation = game.get_frame(model)
            action = robot.get_action(observation)
            print ('> Action', action)
            reward, observation2, terminal = game.feedback(action, model)
            print ('> Reward', reward)
            robot.update(observation, action, reward, observation2, terminal)
            if terminal == True:
                episode += 1
                print ('> Terminal <')
    return (robot, game, model)

def test_agent_batch(robot, game, model, budget):
    i = 0
    queried_x = []
    queried_y = []
    performance = []
    cost = []
    test_sents = helpers.data2sents(game.test_x, game.test_y)
    game.replay()
    while i < budget:
        sel_ind = game.current_frame
        # construct the observation
        observation = game.get_frame(model)
        action = robot.get_action(observation)
        if action[1] == 1:
            sentence = game.train_x[sel_ind]
            labels = game.train_y[sel_ind]
            queried_x.append(sentence)
            queried_y.append(labels)
            i += 1
            train_sents = helpers.data2sents(queried_x, queried_y)
            model.train(train_sents)
            performance.append(model.test(test_sents))
            cost.append(i)
        game.current_frame += 1
    print ('***COST', cost)
    print ("***TEST", performance)
    return (cost, performance)


def test_agent_online(robot, game, model, budget):
    # to address game -> we have a new game here
    i = 0
    queried_x = []
    queried_y = []
    performance = []
    test_sents = helpers.data2sents(game.test_x, game.test_y)
    game.reboot()
    while i < budget:
        sel_ind = game.current_frame
        # construct the observation
        observation = game.get_frame(model)
        action = robot.get_action(observation)
        if action[1] == 1:
            sentence = game.train_x[sel_ind]
            labels = game.train_y[sel_ind]
            queried_x.append(sentence)
            queried_y.append(labels)
            i += 1
            train_sents = helpers.data2sents(queried_x, queried_y)
            model.train(train_sents)
            performance.append(model.test(test_sents))

        reward, observation2, terminal = game.feedback(action, model)  # game
        robot.update(observation, action, reward, observation2, terminal)
    # train a crf and evaluate it
    train_sents = helpers.data2sents(queried_x, queried_y)
    model.train(train_sents)
    performance.append(model.test(test_sents))
    print ("***TEST", performance)

parser = argparse.ArgumentParser()
parser.add_argument('--source', help="datasource", default='conll')
parser.add_argument('--agent', help="require a decision agent")
parser.add_argument('--episode', type=int, help="require a maximum number of playing the game", default=20)
parser.add_argument('--budget', type=int, help="requrie a budget for annotating", default=75)
args = parser.parse_args()

global AGENT, MAX_EPISODE, BUDGET, TRAIN_LANG, TEST_LANG, TRAIN_LANG_NUM, TEST_LANG_NUM
SOURCE = args.source
AGENT = args.agent
MAX_EPISODE = args.episode
BUDGET = args.budget
 
flags = tf.flags
FLAGS = flags.FLAGS
flags.DEFINE_integer("max_seq_len", 120, "sequence")
flags.DEFINE_integer("max_vocab_size", 20000, "vocabulary")
print("\nParameters:")
for attr, value in FLAGS.flag_values_dict().items():
    print("{}={}".format(attr.upper(), value))
print("")

DATAPATH = './datasets/{}'.format(SOURCE)
train_f  = DATAPATH + '.train'
test_f   = DATAPATH + '.test'
dev_f    = DATAPATH + '.dev'
emb_f    = DATAPATH + 'NUM.kv'
tagger_f = DATAPATH + AGENT + 'model.saved'

TRAIN_LANG = []
TEST_LANG = []
TRAIN_LANG_NUM = 1
TRAIN_LANG.append((train_f, test_f, dev_f, emb_f, tagger_f))
TEST_LANG_NUM = 1
TEST_LANG.append((train_f, test_f, dev_f, emb_f, tagger_f))

# play games for training a robot
robot, game, model = play_ner()
cost_list, acc_list = test_agent_batch(robot, game, model, BUDGET)
acc_valid_list = acc_list
print (SOURCE)
with open("./results/{}-{}-{}.bin".format(AGENT, SOURCE, MAX_EPISODE), "wb") as result:
    pickle.dump((cost_list, acc_list, acc_valid_list), result)

import re
import time
import copy
import configparser
from datetime import date, timedelta
from amazon_client.amazon_selenium_client import AmazonSeleniumClient
from actual_client import ActualClient

config = configparser.ConfigParser()
config.read("secrets/credentials.ini")
myConfig = config['DEFAULT']

otpSecret = myConfig["otpSecret"]
userEmail = myConfig["userEmail"]
userPassword = myConfig["userPassword"]
actualBaseUrl = myConfig["actualBaseUrl"]
actualToken = myConfig["actualToken"]

def main(amazonClient):
    orderIDs = amazonClient.getAllOrderIDs(3)
    amazonT = []

    for orderID in orderIDs:
        try:
            iPage = amazonClient.getInvoicePage(orderID)
            afterTaxItems, transactions = parser.parseInvoicePage(iPage)
            if afterTaxItems is None or transactions is None:
                continue
            matched = matcher.matchAmazonTransactions(afterTaxItems, transactions)
            amazonT.append(matched)
        except Exception as e:
            print(f"Something went wrong processing order {orderID}: {e}")

    actualClient = ActualClient(actualBaseUrl, actualToken)
    actualT = actualClient.list_recent_transactions(30)
    transactions = matcher.matchAmazonToYNAB(amazonT, actualT)
    actualClient.update_transactions(transactions)

if __name__ == "__main__":
    amazonSeleniumClient = AmazonSeleniumClient(userEmail, userPassword, otpSecret)
    main(amazonSeleniumClient)

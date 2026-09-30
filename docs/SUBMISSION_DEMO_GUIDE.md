# Submission demo guide

## What the project already contains

The project has a repeatable fictional school-data seed. It is designed for demonstration records, not to represent real student data. Use the existing records instead of generating new records to make the dataset look real.

## For today's submission

1. Use the existing seeded school records and describe them as synthetic demonstration data.
2. Show the current Firebase SMS failure (`auth/error-code:-39`) accurately. The portal did not confirm that an SMS code was sent.
3. On the sign-in page, choose **Email** as the verification method before submitting the credentials. The existing Email OTP flow sends its code to that account's registered email and remains separate from SMS. Do not describe an email-delivered code as an SMS code.
4. Do not change a production student's or teacher's phone number just to make an OTP demo work. The existing seed already defines a 486-student fictional roster; select records from it for the walkthrough instead of adding duplicate records.

Suggested explanation:

> The portal's Firebase Phone Auth flow is configured, but Firebase returned internal error 39 during the live SMS request. The school records shown are synthetic demo data. I can demonstrate the email verification path, and I will show the Firebase test-number flow separately without claiming that a real SMS was sent.

## Optional Firebase test-number demo (staging only)

Firebase supports fictional phone numbers with preset verification codes. This tests the Firebase phone-authentication flow without sending SMS or consuming SMS quota. It is not evidence that live SMS delivery works.

1. Use a separate staging/local database and a dedicated demo account. Do not change a real or production account's phone number for this test.
2. In Firebase Console, open **Authentication → Sign-in method → Phone numbers for testing**.
3. Add an unused fictional test number and a six-digit code. Use a number from Firebase's documented test-number examples or another number explicitly reserved for testing; never use a real person's number.
4. Set that same test number on the dedicated staging demo account, in E.164 format.
5. Sign in to the staging portal, choose the SMS test flow, and enter the configured test code. Tell the evaluator that Firebase sends no SMS for this number.
6. After the demo, remove the test number/code from Firebase and keep the account confined to staging.

Leave `appVerificationDisabledForTesting` off in production. Do not put test codes, test-number bypasses, or email-relayed SMS codes into the production login flow.

Firebase's instructions and limits for fictional phone numbers: <https://firebase.google.com/docs/auth/web/phone-auth#test-with-fictional-phone-numbers>.
